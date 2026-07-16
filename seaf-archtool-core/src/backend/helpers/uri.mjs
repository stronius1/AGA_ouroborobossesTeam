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
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2023
      Alexander Romashin <romashin.a.va@sberbank.ru>, Sber - 2025
*/

import uriToolConstructor from '@global/manifest/tools/uri.mjs';

/**
 * Добавить протокол file:/// если другого протокола не указано
 */
export function addFileProtocolIfNoProtocol(url) {
    if (!url.includes(':')) { // если нет протокола (двоеточия), то пробуем работать как с файлом
        url = `file:///${url}`;
    }
    return url;
}

const config = {
    gitlab_server: process.env.VUE_APP_DOCHUB_GITLAB_URL,
    bitbucket_server: process.env.VUE_APP_DOCHUB_BITBUCKET_URL,
    personalToken: process.env.VUE_APP_DOCHUB_PERSONAL_TOKEN,
    bitbucketMode: process.env.VUE_APP_DOCHUB_BITBUCKET_MODE,
    bitbucketAdapterUrl: process.env.VUE_APP_DOCHUB_BITBUCKET_ADAPTER_URL
};

export default new uriToolConstructor(config);
