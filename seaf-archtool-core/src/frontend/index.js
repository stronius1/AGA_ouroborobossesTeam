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
      Navasardyan Suren, Sber - 2023
      R.Piontik <r.piontik@mail.ru> - 2023
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2024
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
      Artyom Prilip <artyom.prilip@gmail.com>, Sber - 2026
*/

// See icons https://fonts.google.com/icons?selected=Material+Icons
import '@assets/styles/material_icons.css';
import '@assets/styles/main.css';
import '@/node_modules/@mdi/font/css/materialdesignicons.min.css';
import 'swagger-ui/dist/swagger-ui.css';
import 'vuetify/styles';
import 'vue-toastification/dist/index.css';
import userRightStore from '@front/store/userRightStore.js';
import { processingOrgCtx } from '@front/helpers/orgCtxOnPageHelper.mjs';
import { registerArchLoadEvent } from '@front/helpers/archLoader.js';
import { aliases, mdi } from 'vuetify/iconsets/mdi';

import Axios from 'axios';
import { createApp } from 'vue';
import { createVuetify } from 'vuetify';
import * as components from 'vuetify/components';
import * as directives from 'vuetify/directives';
import { createStore } from 'vuex';
import { setPluginsStoreAppInstance } from './plugins/plugins';
import GlobalMixin from '@front/mixins/global';
import gitlab from '@front/storage/gitlab';
import '@idea/papi';
import VsCode from '@vscode';
import router from './router';
import '@front/storage/indexedDB';
import { UserManager, getOidcSettings } from '@front/oidc-settings';
import { registerJsonataVersionFunction } from '@front/helpers/jsonata/versionsFunc';
import { getLoggerWithTag } from '@global/logger/v2/logger.mjs';
import userStore from '@front/store/userStore.js';
import { enableClickstream } from '@front/clickstream/clickstream';
import env from '@front/helpers/env';

import Root from '@front/components/Root.vue';
import Aspect from '@front/components/Architecture/Aspect.vue';
import Component from '@front/components/Architecture/Component.vue';
import Context from '@front/components/Architecture/Context.vue';
import DocHubDoc from '@front/components/Docs/DocHubDoc.vue';
import PlantUML from '@front/components/Schema/PlantUML.vue';
import Radar from '@front/components/Techradar/Main.vue';
import Technology from '@front/components/Techradar/Technology.vue';
import Anchor from '@front/components/Tools/Anchor.vue';
import Image from '@front/components/Tools/Image.vue';
import Youtube from '@front/components/Tools/Youtube.vue';
import Entity from '@front/components/Entities/Entity.vue';
import DocHubObject from '@front/components/Docs/DocHubObject';
import DatePicker from '@front/components/Tools/DatePicker/DatePicker.vue';
import { ErrorBoundary } from '@front/shared/ErrorBoundary';

function installGlobalComponents(app) {
  // Прокидываем instance приложения в стор плагинов
  setPluginsStoreAppInstance(app);

  app.mixin(GlobalMixin);
  app.config.compilerOptions.isCustomElement = (tag) => tag === 'asyncapi-component';

  app.component('ErrorBoundary', ErrorBoundary);
  app.component('DochubAnchor', Anchor);
  app.component('DochubImage', Image);
  app.component('DochubYoutube', Youtube);
  app.component('DochubEntity', Entity);
  app.component('DochubObject', DocHubObject);
  app.component('DochubContext', Context);
  app.component('DochubDoc', DocHubDoc);
  app.component('DochubComponent', Component);
  app.component('DochubAspect', Aspect);
  app.component('DochubTechnology', Technology);
  app.component('DochubRadar', Radar);
  app.component('DochubPlantuml', PlantUML);
  app.component('DochubDatePicker', DatePicker);
}

const logger = getLoggerWithTag('f/index');

window.Router = router;

if (env.isBackendMode) {
  // эти запросы можно запустить параллельно, чтобы не ждать последовательно.
  await Promise.allSettled([
    env.updateBackendEnv(),
    userRightStore.initRightData()
  ]);

  if (env.archChooserEnabled) {
    processingOrgCtx();
  }
}

const odicSettings = getOidcSettings();

window.OidcUserManager = new UserManager(odicSettings);

await userStore.initUserData();
console.log('User data:', userStore.getUserData());

if (window.DochubVsCodeExt) {
  VsCode.pipe();
}

const store = createStore(gitlab);
window.Vuex = store;
store.$axios = Axios;

// TODO: не понятно, почему для vscode используется именно этот store
if (window.DochubVsCodeExt) {
  VsCode.listener(store);
}

const vuetify = createVuetify({
  components,
  directives,
  icons: {
    defaultSet: 'mdi',
    aliases,
    sets: {
      mdi
    }
  },
  defaults: {
    VIcon: {
      color: 'rgba(0, 0, 0, 0.54)'
    }
  },
  theme: {
    defaultTheme: 'light'
  }
});

if (!env.isPlugin()) {
  void enableClickstream();
} else {
  logger.info(() => 'In plugin: запуск clickstream будет позже, после получения настроек');
}

registerJsonataVersionFunction();
registerArchLoadEvent();

export default {
  router,
  vuetify,
  store,
  createApp,
  Root,
  Axios,
  installGlobalComponents
};
