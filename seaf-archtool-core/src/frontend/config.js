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
*/

import env from '@front/helpers/env';
import { enableClickstream } from '@front/clickstream/clickstream';
import { getLoggerWithTag } from '@global/logger/v2/logger.mjs';
import { addPapiSettingUpdateCallbacks } from '@ide/papiLifeCycle';

const logger = getLoggerWithTag('f/config');
logger.info(() => 'MAIN ENVIRONMENTS:');

const hiddenEnvs = [];

for(const key in env.dochub) {
  logger.info(() => `  ${key}=${hiddenEnvs.indexOf(key) < 0 ? JSON.stringify(env.dochub[key]) : '**HIDDEN**'}`);
}

const config = {};

const reloadConfig = () => {
  if (env.gitlabUrl || env.bitbucketUrl) {
    if (env.gitlabUrl) {
      config.gitlab_server = env.gitlabUrl;
    }
    if (env.bitbucketUrl) {
      config.bitbucket_server = env.bitbucketUrl;
      config.bitbucketMode = env.bitbucketMode;
      config.bitbucketWriterMode = env.bitbucketWriterMode;
    }
    config.personalToken = env.personalToken;
    config.oauth = false;
  }

  void enableClickstream();
};

addPapiSettingUpdateCallbacks({
  funcName: 'reload config.js',
  func: () => reloadConfig()
});

// прямой вызов если мы запущены не как плагин
if (!env.isPlugin()) {
  reloadConfig();
}

export default config;
