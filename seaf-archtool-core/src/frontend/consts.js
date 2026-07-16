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
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2025
      Rostislav Kabalin <kabalin2009@yandex.ru> - 2022
*/

export default {
	plugin: {
		ROOT_MANIFEST: 'plugin:/idea/source/$root'
	},
	pages: {
		OAUTH_CALLBACK_PAGE: '/sso/gitlab/authentication',
		MAIN_PAGE: '/main'
	},
	plantuml: {
		DEFAULT_SERVER: 'seaf.slsdev.ru/seafplantuml/svg/',
    ORIGIN: 		    `${window.origin}/plantuml/svg/`
	},
	transports: {
		HTTP: 'http',
		GITLAB: 'gitlab'
	},
	events: {
		CHANGED_SOURCE: 'on-changed-source'
	},
  clickstream: {
    // Время ожидания появления новых компонентов перед отправкой в clickstream
    MARKDOWN_WAIT_SUBDOC_RENDER_MS: 1000
  },
	roleModelV2: {
		urlAliasParamName: '_sfa-orgctx',
		urlOriginAliasParamName: '_sfa-origin-orgctx'
	}
};

