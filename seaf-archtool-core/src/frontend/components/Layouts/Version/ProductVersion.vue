<!--
  Copyright (C) 2022 Sber

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

  In any derivative products, you must retain the information of
  owner of the original code and provide clear attribution to the project

  https://dochub.info

  The use of this product or its derivatives for any purpose cannot be a secret.


  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.

  Maintainers:
    Sergeev Viktor, Sber - 2025

  Contributors:
    Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
-->

<template>
  <div class="version-container">
    <div class="version-column" v-on:click="copyAppInfoToClipboard">
      <div v-for="(version, index) in displayVersions" v-bind:key="index" class="version-item">{{ version }}</div>
    </div>
  </div>
</template>

<script>

  import copyToClipboard from '@front/helpers/clipboard';
  import env from '@front/helpers/env';
  import requests from '@front/helpers/requests';
  import manifestParser from '@front/manifest/manager';
  import ServerUpdatedToast from './ServerUpdatedToast';
  import {getLoggerWithTag} from '@global/logger/v2/logger';
  import {useToast} from 'vue-toastification';

  const CHECK_VERSION_DEFAULT_INTERVAL = 1000;
  const VERSION_RQ_URL = 'backend://versions';

  const logger = getLoggerWithTag('ProductVersion');
  const toast = useToast();

  export default {
    name: 'ProductVersion',

    data() {
      return {
        displayVersions: null,
        copiedVersions: false
      };
    },

    mounted() {
      this.checkVersionInterval = CHECK_VERSION_DEFAULT_INTERVAL;
      this.versionChecker = null;
      this.versionsCache = null;
      this.newVersions = null;
      this.waitIdeSettings()
        .then(() => {
          this.displayVersions = ['then'];
          if(!env.isBackendMode) {
            // если мы не в режиме backend/cluster, то надо дождаться пока манифест будет собран
            // и только после этого собирать версии
            manifestParser.registerAfterLoadedCallback('ProductVersion.initVersionChecker', this.initVersionChecker);
          } else {
            this.initVersionChecker();
          }
        }).catch(e => {
          logger.error(() => 'error mounted version info', e);
          this.displayVersions = ['mounted error'];
        });
    },

    methods: {
      copyAppInfoToClipboard() {
        copyToClipboard(JSON.stringify(
          {
            ...this.versionsCache,
            copyTimestamp: new Date().toISOString()
          }
        ));
        const tmpDisplayVersions = this.displayVersions;
        this.displayVersions = ['Скопировано ✔'];
        this.copiedVersions = true;
        setTimeout(() => {
          this.copiedVersions = false;
          this.displayVersions = tmpDisplayVersions;
        }, 3000); // на 3 секунд меняем иконку
      },

      /**
       * Ожидаем настройки ide с версией. Если запущены не в плагине, то шаг пропускается
       */
      waitIdeSettings() {
        if (!env.isPlugin()) {
          return Promise.resolve();
        }
        return new Promise((resolve) => {
          const interval = setInterval(() => {
            this.displayVersions = ['wait ide setting'];
            const ideSettings = env.ideSettings;
            if (ideSettings) { // если настройки получены от ide
              logger.trace(() => 'ide settings success receive');
              clearInterval(interval); // останавливаем ожидание и завершаем promise
              this.displayVersions = ['ide setting receive'];
              resolve();
            }
          }, 500); // запускаем таймер в ожидании настроек ide
        });
      },
      /**
       * Создаем дебаг информацию, об используемых версиях для копирования пользователем
       * @param versions - версии пакетов и хеш данных на беке (при наличии)
       */
      setDebugData(versions) {
        try {
          const pluginVersion = env.pluginVersion;
          const pluginName = env.pluginName;
          const mode = env.isPlugin() ? 'plugin' : env.isBackendMode ? 'portal' : 'fat_client';
          const pluginMode = env.pluginMode;
          this.versionsCache = {
            coreVersion: versions.coreVersion,
            pluginVersion: pluginVersion,
            pluginName: pluginName,
            metamodels: versions.metamodels,
            settings: {
              mode: mode,
              pluginMode: pluginMode
            },
            logLevel: env.logLevel,
            pageOpenTimestamp: new Date().toISOString()
          };
          versions.archHash && (this.versionsCache.archHash = versions.archHash);
          this.displayVersions = [
            `core: ${versions.coreVersion}`
          ];
          if (pluginName) {
            this.displayVersions.push(`${pluginName}: ${pluginVersion}`);
          }
        } catch (e) {
          logger.error(() => 'error when set version info', e);
          this.displayVersions = ['error get version info'];
        }
      },
      /**
       * Проверка новой версии, если версия изменилась, отменяем последующие проверки (т.к. нам важен первый факт
       * изменения версии, последующие не важны)
       */
      async updateVersion() {
        try {
          const versions = await this.requestToBackend();
          if (versions.archHash !== this.versionsCache.archHash || versions.coreVersion !== this.versionsCache.coreVersion) {
            this.newVersions = versions;
            this.versionsCache.needRefreshPage = true;
            toast.warning(ServerUpdatedToast, {
              position: 'bottom-left',
              timeout: false,
              closeOnClick: false,
              pauseOnFocusLoss: true,
              pauseOnHover: true,
              draggable: true,
              draggablePercent: 0.6,
              showCloseButtonOnHover: true,
              hideProgressBar: true,
              closeButton: 'button',
              rtl: false
            });
          }
          // Если всё прошло успешно — сбрасываем интервал в норму
          this.checkVersionInterval = CHECK_VERSION_DEFAULT_INTERVAL;
        } catch (err) {
          logger.debug(() => 'Error when check version', err); // в дебаг потому что не критично
          // Увеличиваем интервал (например, ×2), но с лимитом
          this.checkVersionInterval = Math.min(this.checkVersionInterval * 2, 60000);
        }
        if (!this.newVersions) { // если версия не изменилась, повторяем запрос периодически
          setTimeout(() => this.updateVersion(), this.checkVersionInterval);
        }
      },

      /**
       * Запрашиваем текущую версию, и запускаем процесс мониторинга обновления версии, если запущены как backend/cluster
       */
      async initVersionChecker() {
        this.displayVersions = ['initVersionChecker'];
        if (this.versionsCache) {
          this.displayVersions = ['versionsCache not null'];
          return;
        }
        if (!env.isBackendMode) {
          this.displayVersions = ['set ui versions'];
          this.setDebugData(this._buildVersionOnUi());
          return;
        }
        this.displayVersions = ['wait backend setting'];
        let versions = await this.requestToBackend();
        this.displayVersions = ['backend setting receive'];
        this.setDebugData(versions);
        if (versions.enableChecker && !this.versionChecker) {
          this.versionChecker = setTimeout(() => this.updateVersion(), this.checkVersionInterval);
        }
      },

      async requestToBackend() {
        let newVar = await requests.request(VERSION_RQ_URL);
        return newVar.data;
      },

      _buildVersionOnUi() {
        return {
          coreVersion: __APP_VERSION__,
          metamodels: manifestParser.metamodels,
          archHash: undefined
        };
      }
    }
  };
</script>

<style>
.version-container {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-right: 16px;
}

.version-column {
  display: flex;
  flex-direction: column;
}

.version-item {
  font-size: 0.75rem;
  line-height: 1;
  color: #ccc;
}
</style>
