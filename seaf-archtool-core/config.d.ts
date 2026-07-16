/*
  Copyright (C) 2026 Sber

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
      Nikolay Temnyakov <temnjakovn@gmail.com>, Sber - 2026
*/

// eslint-disable-next-line no-var
declare var DochubVsCodeExt: {
  metamodelUri: {
    $mid: number;
    authority: string;
    path: string;
    scheme: string;
  };

  rootManifest: string,
  settings: {
    isEnterprise: boolean,    // Признак использования фронта в плагине как Enterprise портала
    enterpriseServer?: string,
    pluginVersion?: string,
    render: {
      external: boolean,
      mode: string,
      request_type: string,
      server: string
    };
    env: {                    // Переменные среды для IDE режима
      DOCHUB_IDE_GITLAB_URL?: string,     // gitlab сервер для режима IDE
      DOCHUB_IDE_BITBUCKET_URL?: string,  // bitbacket сервер для режима IDE
      DOCHUB_IDE_PERSONAL_TOKEN?: string, // персональный токен для gitlab/bitbacket
      DOCHUB_IDE_BITBUCKET_MODE?: string, // bitbacket mode: "None","v1", "v2", "adapter"
    };
    gigachatCredential: string;
    gigachatScope: string;
    gigachatDefaultModel: string;
    gigachatTimeout: number;
    logLevel: string;
    isJsonataLogFuncEnable: boolean;
    additionalEnv: string;
    isCacheMode: boolean;
  }
};

// eslint-disable-next-line no-var
declare var DocHubIDEACodeExt: {
  rootManifest: string,       // Корневой манифест (с чего начинается загрузка)
  settings: {
    [x: string]: {};
    isEnterprise: boolean,    // Признак использования фронта в плагине как Enterprise портала
    enterpriseServer?: string,
    pluginVersion?: string,
    render: {
      external: boolean,      // Признак рендера на внешнем сервере
      mode: string,           // Режим рендера ELK / Smetana / GraphVis
      request_type: string,   // Тип запросов к сервер рендеринга POST / GET
      server: string          // Сервер рендеринга
    };
    env: {                    // Переменные среды для IDE режима
      DOCHUB_IDE_GITLAB_URL?: string,     // gitlab сервер для режима IDE
      DOCHUB_IDE_BITBUCKET_URL?: string,  // bitbacket сервер для режима IDE
      DOCHUB_IDE_PERSONAL_TOKEN?: string, // персональный токен для gitlab/bitbacket
      DOCHUB_IDE_BITBUCKET_MODE?: string, // bitbacket mode: "None","v1", "v2", "adapter"
    };
    gigachatCredential: string;
    gigachatScope: string;
    gigachatDefaultModel: string;
    gigachatTimeout: number;
    logLevel: string;
    isJsonataLogFuncEnable: boolean;
    additionalEnv: string; // Строка с любыми env для переопределения, когда не делаем отдельную настройку, но оставляем возможность поменять значение
    isCacheMode: boolean;
    s3CloudUrl: string;
    usingS3Mode: boolean;
  }
};

// В additionalEnv храним переопределение env переменных, такое временное хранилище для любых переменных,
// пока им не выделено отдельная переменная в DocHubIDEACodeExt или DochubVsCodeExt.
// Тут хранятся ключ-значение переданные из настроек IDE
// eslint-disable-next-line no-var
declare var additionalIdeEnv: Record<string, string>;

declare const vscode: {
  postMessage: ({
    command,
    content
  }: {
    command: string,
    content: any
  }) => Promise<any> | void
};

interface Window { $PAPI: any; }

/**
 * Версия приложения взятая из package.json
 */
declare const __APP_VERSION__: string;
