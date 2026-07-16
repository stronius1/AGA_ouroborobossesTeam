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
      Rostislav Kabalin <kabalin2009@yandex.ru> - 2022
      R.Piontik <r.piontik@mail.ru> - 2023
      Artyom Prilip <artyom.prilip@gmail.com>, Sber - 2026
-->

<template>
  <v-app
    id="keep"
    class="app"
    v-bind:class="{'no-select-text': isDrawerResize}">
    <v-layout class="full-height">
      <header-component v-on:handleDrawer="handleDrawer" />

      <v-navigation-drawer
        ref="drawer"
        v-model="drawer"
        class="app-navigation-drawer"
        v-bind:width="width"
        v-bind:temporary="navIsTemporary"
        style="z-index: 999">
        <menu-component />
      </v-navigation-drawer>

      <plugin-init v-if="isNotInited" />

      <v-main v-else class="router-view scroll-bar">
        <problems v-if="isCriticalError" />
        <router-view v-else />
      </v-main>
    </v-layout>

    <template v-if="isLoading">
      <div class="loading-splash" />
      <v-progress-circular
        class="whell"
        v-bind:size="64"
        v-bind:width="7"
        v-bind:model-value="60"
        color="primary"
        indeterminate />
    </template>
  </v-app>
</template>

<script>
  import PluginInit from '@idea/components/Init.vue';
  import env from '@front/helpers/env';

  import MenuComponent from './Layouts/Menu';
  import HeaderComponent from './Layouts/Header';
  import Problems from './Problems/Problems.vue';

  const minDrawerSize = 200;
  const defaultDrawerSize = 300;

  export default {
    name: 'Root',
    components: {
      MenuComponent,
      HeaderComponent,
      PluginInit,
      Problems
    },
    data() {
      return {
        drawer: null,
        isDrawerResize: false,
        width: defaultDrawerSize,
        isPlugin: env.isPlugin()
      };
    },
    computed: {
      isLoading() {
        return this.$store.state.isReloading;
      },
      isNotInited() {
        return this.isPlugin && this.$store.state.notInited;
      },
      isCriticalError() {
        return this.isPlugin && this.$store.state.criticalError;
      },
      navIsTemporary() {
        return this.$store.state.isPrintVersion;
      }
    },
    mounted() {
      const el = this.$refs.drawer.$el.nextElementSibling?.matches('.v-navigation-drawer')
        ? this.$refs.drawer.$el.nextElementSibling
        : document.querySelector('.v-navigation-drawer');
      if (!el) return;

      const drawerBorder = document.querySelector('.v-navigation-drawer__border');

      const resize = (e) => {
        document.body.style.cursor = 'ew-resize';
        if (e.clientX < minDrawerSize) return;
        this.width = e.clientX;
      };

      drawerBorder && drawerBorder.addEventListener(
        'mousedown',
        (e) => {
          if (e.offsetX < minDrawerSize) {
            el.style.transition = 'initial';
            document.addEventListener('mousemove', resize, false);
            this.isDrawerResize = true;
          }
        },
        false
      );

      document.addEventListener(
        'mouseup',
        () => {
          if (!this.isDrawerResize) return;

          el.style.transition = '';
          document.body.style.cursor = '';
          document.removeEventListener('mousemove', resize, false);
          this.isDrawerResize = false;
        },
        false
      );
    },
    methods: {
      handleDrawer(value) {
        this.drawer = value ?? !this.drawer;
      }
    }
  };
</script>

<style>
  .app {
    height: 100vh;

    @media print {
      height: unset;
    }
  }

  .router-view {
    overflow: auto;
    max-height: 100%;

    @media print {
      overflow: unset;
      max-height: unset;
    }
  }

  .router-view::-webkit-scrollbar-track {
    -webkit-box-shadow: inset 0 0 6px rgba(0, 0, 0, 0.3);
    border-radius: 8px;
    background-color: #f5f5f5;
  }
  .router-view::-webkit-scrollbar {
    width: 14px;
    height: 14px;
    background-color: #f5f5f5;
  }
  .router-view::-webkit-scrollbar-thumb {
    border-radius: 8px;
    -webkit-box-shadow: inset 0 0 6px rgba(0, 0, 0, 0.3);
    background-color: rgba(0, 117, 94, 0.75);
  }

  .swagger-ui {
    width: 100%;
  }

  .router-view {
    max-height: 100%;
  }

  .router-view > div,
  .router-view > div > div,
  .router-view > div > div > div {
    height: 100%;
  }

  .v-navigation-drawer__border {
    width: 3px !important;
    cursor: col-resize !important;
    background: #ccc !important;
  }

  .no-select-text * {
    user-select: none;
    -moz-user-select: none;
    -webkit-user-select: none;
    -ms-user-select: none;
  }

  .loading-splash {
    background: #fff;
    opacity: 0.7;
    z-index: 10;
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    right: 0;
    filter: blur(8px);
    -webkit-filter: blur(8px);
  }

  .whell {
    z-index: 100;
    left: 50%;
    top: 50vh;
    position: absolute !important;
    margin-left: -32px;
    margin-top: -32px;
  }

  ::selection {
    background-color: #3495db;
    color: #fff;
  }

  .full-height {
    height: 100%;
  }
</style>
