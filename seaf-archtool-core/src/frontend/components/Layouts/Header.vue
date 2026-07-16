<!--
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
      Navasardyan Suren, Sber - 2023
      Nikolay Temnyakov <temnjakovn@gmail.com>, Sber - 2026
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2024
      Vladislav Nefedov <clay.zenx@gmail.com>, Sber - 2024
      R.Piontik <r.piontik@mail.ru> - 2023
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
-->

<template>
  <v-app-bar
    app
    clipped-left
    color="#00755D"
    v-bind:class="isPrintVersion ? 'print-version' : ''"
    style="z-index: 99">
    <div class="main-layout__header">
      <div class="main-layout__header__menu">
        <v-app-bar-nav-icon v-on:click="() => handleDrawer()">
          <menu-icon style="padding: 5px 6px 4px 4px" />
        </v-app-bar-nav-icon>
        <div class="main-layout__header__menu__logo" style="cursor: pointer" v-on:click="onLogoClick">
          <header-logo />
          <v-toolbar-title>{{ title }}</v-toolbar-title>
        </div>
        <product-version />
        <v-btn v-if="isBackShow" icon v-on:click="back">
          <v-icon>mdi-arrow-left</v-icon>
        </v-btn>
        <v-btn v-if="isBackShow" icon v-on:click="debug">
          <v-icon>mdi-bug</v-icon>
        </v-btn>
        <v-btn v-if="isBackShow" icon v-on:click="refresh">
          <v-icon>mdi-refresh</v-icon>
        </v-btn>
      </div>
      <div class="main-layout__header__menu main-layout__hide-on-print">
        <div v-if="isRolesMode" style="cursor: pointer">
          <!-- Подключаем новый компонент отображения профиля или кнопку для входа -->
          <initial-avatar v-if="hasUserData" />
          <login-button v-else />
        </div>
        <v-spacer />
        <v-btn v-if="isCriticalError" icon title="Есть критические ошибки!" v-on:click="gotoProblems">
          <v-icon class="blink" style="display: inline">mdi-alert-circle</v-icon>
        </v-btn>
        <v-btn v-if="gotoIconShow" icon title="Найти в коде" v-on:click="gotoCode">
          <v-icon style="display: inline">mdi-code-tags</v-icon>
        </v-btn>
        <v-menu v-model="dotsMenu" location="bottom">
          <template #activator="{ props }">
            <v-btn icon v-bind="props" class="menu-btn">
              <v-icon>mdi-dots-vertical</v-icon>
            </v-btn>
          </template>
          <v-list>
            <file-status-center
              v-if="isFilesFeatureEnabled"
              activator="menu-item"
              menu-title="Статусы загрузки файлов" />
            <v-list-item class="main-layout__header__menu-item">
              <v-checkbox v-model="isPrintVersion" label="Версия для печати" />
            </v-list-item>
            <v-list-item class="main-layout__header__menu-item">
              <v-list-item-title style="cursor: pointer;" v-on:click="doPrint">Печать</v-list-item-title>
            </v-list-item>
          </v-list>
        </v-menu>
      </div>
    </div>
  </v-app-bar>
</template>

<script>
  import env, {Plugins} from '@front/helpers/env';


  import InitialAvatar from '@front/components/Account/InitialAvatar.vue';
  import LoginButton from '@front/components/Account/LoginButton.vue';
  import FileStatusCenter from '@front/components/Account/FileStatusCenter.vue';

  import HeaderLogo from './HeaderLogo';
  import MenuIcon from './MenuIcon';
  import ProductVersion from './Version/ProductVersion';
  import userStore from '@front/store/userStore.js';

  export default {
    name: 'Header',
    components: {
      InitialAvatar,
      HeaderLogo,
      MenuIcon,
      LoginButton,
      ProductVersion,
      FileStatusCenter
    },
    data() {
      return {
        isBackShow: env.isPlugin(Plugins.vscode),
        dotsMenu: false,
        title: env.projectTitle
      };
    },
    computed: {
      hasUserData() {
        return userStore.isAuthenticated();
      },
      isRolesMode() {
        return env.isBackendMode && env.isRolesMode;
      },
      isFilesFeatureEnabled() {
        return env.usingS3Mode;
      },
      gotoIconShow() {
        return env.isPlugin() && this.$route.name === 'entities';
      },
      isCriticalError() {
        return !!(this.$store.state.problems || []).find((item) => item.critical);
      },
      isPrintVersion: {
        set(value) {
          this.handleDrawer(!value);
          this.$store.commit('setPrintVersion', value);
        },
        get() {
          return this.$store.state.isPrintVersion;
        }
      },
      isFullScreenMode: {
        set(value) {
          this.$store.commit('setFullScreenMode', value);
        },
        get() {
          return this.$store.state.isFullScreenMode;
        }
      }
    },
    methods: {
      doPrint() {
        this.dotsMenu = false;

        setTimeout(() => {
          if(env.isPlugin(Plugins.vscode)) {
            window.$PAPI.print();
          } else window.print();
        }, 50);
      },
      handleDrawer(value) {
        this.$emit('handleDrawer', value);
      },
      back() {
        this.$router.back();
      },
      gotoProblems() {
        this.$router.push({name: 'problems'}).catch(() => null);
      },
      debug() {
        window.$PAPI.debug();
      },
      async refresh() {
        const currentRoute = { path: this.$route.path, query: this.$route.query };
        await window.$PAPI.reload(currentRoute);
      },
      onLogoClick() {
        this.$router.push({name: 'main'}).catch(() => null);
      },
      gotoCode() {
        const location = window.location;
        const struct = window.location.hash.split('/');
        const entity = struct?.[2];
        const url = new URL(location.hash.slice(1), location);

        // Пытаюсь извлечь идентификатор из параметра содержащем "id" или "domain" (для berezka)
        // или в качестве идентификатора берется хвост от urlа
        // TODO: надо переделать
        const idRegex = /\b(\w*id|domain\w*)=([^&\s]+)\b/;
        const id = idRegex.exec(url.search)?.[2] || struct[struct.length -1];

        if(!entity || !id) return false;

        // Запрос в ide на открытие entity c id
        window.$PAPI.goto(null, entity, id);
      }
    }
  };
</script>

<style scoped>

.main-layout__header {
  display: flex;
  justify-content: space-between;
  width: 100%;
}

.main-layout__header__menu {
  display: flex;
  align-items: center;
  gap: 10px;
}

.main-layout__header__menu-item {
  :global(label) {
    color: #000;
  }
}

.main-layout__header__menu__logo {
  display: flex;
  align-items: end;
  gap: 2px;
}

.main-layout__header__menu__logo :global(.v-toolbar-title) {
  color: #fff;
}

.menu-btn {
  z-index: 1;
}

.main-layout__hide-on-print {
  @media print {
    display: none;
  }
}

header.print-version {
  position: absolute;
}

@keyframes blink {
  50% {
    opacity: 0.0;
  }
}

.blink {
  color: #A00 !important;
  animation: blink 1s step-start 0s infinite;
}

</style>
