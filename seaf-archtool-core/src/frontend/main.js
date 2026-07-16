/*
  Copyright (C) 2021 owner Roman Piontik R.Piontik@mail.ru

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
      R.Piontik <r.piontik@mail.ru>

  Contributors:
      R.Piontik <r.piontik@mail.ru> - 2021
      R.Piontik <r.piontik@mail.ru> - 2022
      R.Piontik <r.piontik@mail.ru> - 2023
      Navasardyan Suren, Sber - 2023
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2025
      Vladislav Nefedov <clay.zenx@gmail.com>, Sber - 2024
      Rostislav Kabalin <kabalin2009@yandex.ru> - 2023
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
      Artyom Prilip <artyom.prilip@gmail.com>, Sber - 2026
*/

import { init } from './bootstrap';
import Toast from 'vue-toastification';

import 'vue-toastification/dist/index.css';
import env, {Plugins} from '@front/helpers/env';
import {requestToBackend} from '@front/helpers/backend.api.helper.js';
import {initUiLogger} from '@front/logger/logger';
import {getLogger, getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import {addPapiSettingUpdateCallbacks} from '@ide/papiLifeCycle';
import {initPluginLogger} from '@ide/logger';

initUiLogger();
const logger = getLoggerWithTag('main.js');

const toastOptions = {
  transition: 'Vue-Toastification__fade',
  maxToasts: 2,
  newestOnTop: false
};

addPapiSettingUpdateCallbacks({
  funcName: 'init plugin logger',
  func: () => {
    if (env.isPlugin(Plugins.idea)) {
      logger.info(() => 'Запущены в idea, меняем ui логгер на логгер idea');
      initPluginLogger();
      if (env.logLevel) {
        getLogger().setLevel(env.logLevel);
      }
    } else {
      logger.info(() => 'Запущены в vscode, оставляем ui логгер');
    }
  }
});

document.addEventListener('DOMContentLoaded', async() => {
  const {
    createApp,
    Root,
    router,
    vuetify,
    store,
    Axios,
    installGlobalComponents
  } = await init(process.env);

  const app = createApp(Root);
  app.config.globalProperties.$axios = Axios;

  installGlobalComponents(app);

  app.use(router);
  app.use(vuetify);
  app.use(Toast, toastOptions);
  app.use(store);

  await store.dispatch('init');

  app.mount('#app');

  if(env.isBackendMode) {
    try {
      const data = await requestToBackend('/seaf-core/api/title');

      const headerTitle = document.querySelector('.v-toolbar__title');

      if(headerTitle) {
        headerTitle.textContent = data.title;
      } else logger.warn(() => 'Header title not found');
    } catch(e) {
      logger.error(() => 'Error fetching title', e);
    }
  }

  window.$PAPI?.loaded && window.$PAPI.loaded();
});
