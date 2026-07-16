/*
  Copyright (C) 2023 Sber

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.

  Maintainers:
      Vladislav Markin <markinvy@yandex.ru>, Sber

  Contributors:
      Nikolay Temnyakov <temnjakovn@gmail.com>, Sber - 2025
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2023
*/

import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

const logger = getLoggerWithTag('f/a/oidc-client');

export default {
    login() {
      return window.OidcUserManager.signinRedirect({ state: window.location.href })
        .then(() => {
            logger.info(() => 'Redirecting to login...');
        })
        .catch(error => {
            logger.error(() => 'Login error:', error);
        });
    },
    logout() {
        return window.OidcUserManager.signoutRedirect()
            .then(() => {
                logger.info(() => 'User logged out');
            })
            .catch(error => {
                logger.error(() => 'Logout error:', error);
            });
    },
    async signinCallback() {
        const user = await window.OidcUserManager.signinCallback();

        if (user?.state) {
          window.location.href = user?.state || `${window.origin}/main`;
        } else {
          window.location.reload();
        }
    },
    async getAccessToken() {
      const user = await window.OidcUserManager.getUser();
      if (user?.expired) {
        logger.warn(() => 'Token is missing or expired. Logging out...');
        this.logout();
        return null;
      }
      return user?.access_token;
    },
    async getUser() {
      return await window.OidcUserManager.getUser();
    }
};
