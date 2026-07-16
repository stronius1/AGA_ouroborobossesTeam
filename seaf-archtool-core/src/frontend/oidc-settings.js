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
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
*/

import {Log, UserManager, WebStorageStateStore} from 'oidc-client-ts';
import env from '@front/helpers/env';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

Log.setLogger(console);
Log.setLevel(Log.ERROR);

const url = window.location.origin;
const logger = getLoggerWithTag('f/oidc-settings');

let settings;

export function getOidcSettings() {
    if (!settings) {
        settings = {
            authority: env.authorityServer,
            client_id: env.authorityClientId,
            redirect_uri: new URL('/login', url),
            post_logout_redirect_uri: new URL('/logout', url),
            response_type: 'code',
            scope: env.authorityScope,
            response_mode: 'fragment',
            automaticSilentRenew: true,
            userStore: new WebStorageStateStore({ store: window.localStorage })
        };

        logger.debug(() => [
            'init oidc settings',
            {title: 'authority' , obj: settings.authority },
            {title: 'client_id' , obj: settings.client_id },
            {title: 'redirect_uri' , obj: settings.redirect_uri },
            {title: 'post_logout_redirect_uri' , obj: settings.post_logout_redirect_uri },
            {title: 'response_type' , obj: settings.response_type },
            {title: 'scope' , obj: settings.scope },
            {title: 'response_mode' , obj: settings.response_mode },
            {title: 'automaticSilentRenew' , obj: settings.automaticSilentRenew }
        ]);
    }
    return settings;
}

export {
    Log,
    UserManager
};
