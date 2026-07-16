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
      R.Piontik <r.piontik@mail.ru> - 2023
      R.Piontik <r.piontik@mail.ru> - 2022
      R.Piontik <r.piontik@mail.ru> - 2021
      Rostislav Kabalin <kabalin2009@yandex.ru> - 2022
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2024
      Vladislav Nefedov <clay.zenx@gmail.com>, Sber - 2023
*/
import cookie from 'vue-cookie';
import { v4 as uuidv4 } from 'uuid';
import env from '@front/helpers/env';
import appRoutes from './routes';
import {
  createRouter,
  createWebHashHistory,
  createWebHistory
} from 'vue-router';
import gateway from '@ide/gateway';
import {
  PAGE_FROM_PATH_SESSION_STORE_KEY,
  PAGE_TO_PATH_SESSION_STORE_KEY,
  PAGE_LOAD_START_SESSION_STORE_KEY,
  ROUTE_UID_SESSION_STORE_KEY
} from '@front/clickstream/clickstream';
import { orgCtxRoutHandler } from '@front/helpers/orgCtxOnPageHelper.mjs';

const routes = [...appRoutes];

if (!env.isPlugin()) {
  routes.push(
    {
      path: '/sso/gitlab/authentication',
      redirect(route) {
        const OAuthCode = Object.keys(route.query).length
          ? route.query.code
          : new URLSearchParams(route.hash.slice(1)).get('code');
        if (OAuthCode) {
          window.Vuex.dispatch('onReceivedOAuthCode', OAuthCode);
          const rRoute = cookie.get('return-route');
          return rRoute ? JSON.parse(rRoute) : {
            path: '/main',
            query: {},
            hash: ''
          };
        } else {
          return {
            path: '/sso/error',
            query: {},
            hash: ''
          };
        }
      }
    }
  );
} else {
  routes.push(
    {
      path: '/url=about:blank',
      redirect() {
        // статический путь для плагина
        window.location.href = new URL('/url=main', window.location.origin).href;
        return { path: '/url=main' };
      }
    }
  );
}

const router = createRouter({
  history: env.isPlugin() ? createWebHashHistory() : createWebHistory(),
  routes,
  scrollBehavior() {
    return { left: 0, top: 0 };
  }
});

router.beforeEach((to, from) => {
  sessionStorage.setItem(
    PAGE_LOAD_START_SESSION_STORE_KEY,
    Date.now().toString()
  );
  sessionStorage.setItem(
    PAGE_FROM_PATH_SESSION_STORE_KEY,
    from.fullPath || 'direct'
  ); // если прямой заход
  sessionStorage.setItem(PAGE_TO_PATH_SESSION_STORE_KEY, to.fullPath);
  sessionStorage.setItem(ROUTE_UID_SESSION_STORE_KEY, uuidv4());
});
router.beforeEach(orgCtxRoutHandler);

gateway.appendListener('navigate/component', (data) => {
  router.push({ path: `/architect/components/${Object.keys(data)[0]}` });
});

gateway.appendListener('navigate/document', (data) => {
  router.push({ path: `/docs/${Object.keys(data)[0]}` });
});

gateway.appendListener('navigate/aspect', (data) => {
  router.push({ path: `/architect/aspects/${Object.keys(data)[0]}` });
});

gateway.appendListener('navigate/context', (data) => {
  router.push({ path: `/architect/contexts/${Object.keys(data)[0]}` });
});

gateway.appendListener('navigate/devtool', (data) => {
  router.push({ path: `/devtool/${Object.keys(data)[0]}` });
});

export default router;
