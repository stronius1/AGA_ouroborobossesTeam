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
      R.Piontik <r.piontik@mail.ru> - 2024
      R.Piontik <r.piontik@mail.ru> - 2023
      R.Piontik <r.piontik@mail.ru> - 2022
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2025
      Rostislav Kabalin <kabalin2009@yandex.ru> - 2022
      Temnyakov Nikolay <temnjakovn@gmail.com>, Sber - 2026
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
*/

import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import {papiSettingUpdated} from '@ide/papiLifeCycle';
import { v4 as uuidv4 } from 'uuid';
import gateway from '@ide/gateway';

const logger = getLoggerWithTag('i/i/papi');
const javaMessageLimit = 15000000; // лимит размера сообщения в логе для отправки в java код

const PAPI = {
  isDebug: false,
  // eslint-disable-next-line no-unused-vars, @typescript-eslint/no-empty-function
  middleware: null,
  settings: {},
  cefQuery: null,
  request(params) {
    const data = JSON.stringify(params);
    // eslint-disable-next-line no-console
    this.isDebug && logger.info(() => `plugin request.request ${data}`);
    return new Promise(function(res, rej) {
      const resolve = function(result) {
        // eslint-disable-next-line no-console
        this.isDebug && logger.info(() => `plugin request.response: ${JSON.stringify(result)}`);
        try {
          const parseData = result || null;
          if (window.$PAPI?.middleware)
            res(window.$PAPI.middleware(JSON.parse(parseData), params));
          else
            res(JSON.parse(parseData));
        } catch (e) {
          rej(e);
        }
      };
      const reject = function(errCode, errInfo) {
        // eslint-disable-next-line no-console
        logger.error(() => `plugin request.error: ${errCode}, ${errInfo}`);
        rej({
          response: {
            data: errInfo,
            headers: {},
            status: errCode
          }
        });
      };

      window.$PAPI.cefQuery({
        request: '' + data,
        onSuccess: resolve,
        onFailure: reject
      });
    });
  },
  renderPlantUML(uml) {
    return this.request({url: 'plugin:/idea/plantuml/svg', source: uml});
  },
  initProject(mode) {
    return this.request({url: 'plugin:/idea/initproject', mode});
  },
  reload() {
    this.request({url: 'plugin:/idea/reload'});
  },
  showDebugger() {
    this.request({url: 'plugin:/idea/debugger/show'});
  },
  goto(source, entity, id) {
    this.request({url: 'plugin:/idea/goto', source, entity, id});
  },
  download(content, title, description, extension, fileName = `dh_${Date.now()}`) {
    this.request({url: 'plugin:/idea/gateway/download', content, title, description, extension, fileName});
  },
  upload() {
    this.request({url: 'plugin:/idea/gateway/upload'});
  },
  applyEntitiesSchema(schema) {
    this.request({url: 'plugin:/idea/entities/applyschema', schema});
  },
  copyToClipboard(data) {
    this.request({url: 'plugin:/idea/clipboard/copy', data});
  },
  // Событие вызывается при необходимости актуализировать конфигурацию DoсHub.
  onReloadSetting() {
    papiSettingUpdated();
  },
  getSettings() {
    return this.request({url: 'plugin:/idea/settings/get'});
  },
  // Сохраняет файл в проекте
  pushFile(source, content) {
    return this.request({url: 'plugin:/idea/code/push/file', source, content});
  },
  // TBD
  pushCode(code, metadata) {
    return this.request({url: 'plugin:/idea/code/push/code', code, metadata});
  },
  invalidateCache() {
    this.request({url: 'plugin:/idea/cache/invalidate'});
  },
  sendLog(logRow) {
    // принимающий java код имеет ограничение
    // JsonMappingException: String value length (20054016) exceeds the maximum allowed (20000000
    if (logRow.message.length > javaMessageLimit) {
      this._sendLogByPart(logRow);
    } else {
      this.request({url: 'plugin:/idea/logs/send', logRow});
    }
  },
  sendJsonataLog(logRow) {
    // принимающий java код имеет ограничение
    // JsonMappingException: String value length (20054016) exceeds the maximum allowed (20000000
    if (logRow.message.length > javaMessageLimit) {
      this._sendLogByPart(logRow);
    } else {
      this.request({url: 'plugin:/idea/logs/jsonata/send', logRow});
    }
  },
  async pullFromCache(key, resolver, args) {
    const result = await this.request({url: 'plugin:/idea/cache/pull', key});
    if (!result.data) {
      const dataset = await resolver(args);
      if(dataset) this.updateCache(key, dataset);
      return dataset;
    }
    return result.data ?? null;
  },
  updateCache(key, data) {
    this.request({url: 'plugin:/idea/cache/update', key, data: JSON.stringify(data)});
  },
  // Запрос к IDE: GET - запрос
  getMetaIntegrationData(url) {
    return this.request({url: 'plugin:/idea/meta/data/request', guid: url});
  },
  // Запрос к IDE: POST - запрос
  postDataInMeta(guid, postURL, data) {
    return this.request({url: 'plugin:/idea/meta/data/post', guid, postURL, data});
  },
  // Запрос к IDE: проверка аутинтификации
  checkIsAuth(backlink) {
    return this.request({url: 'plugin:/idea/meta/auth', backlink});
  },
  checkIsAuthS3(backlink) {
    return this.request({url: 'plugin:/idea/s3/auth', backlink});
  },
  // Запрос к IDE: запуск прокси сервера для библиотеки Гигачат
  startGigachatProxy() {
    return this.request({url: 'plugin:/idea/proxy/start'});
  },
  // Запрос файла из бб проксируемый через idea
  downloadBitBucket(path) {
    return this.request({url: 'plugin:/idea/bitbucket/download', path});
  },
  // Clickstream: сохранить данные по ключу
  setClickstreamData(name, value, ms) {
    return this.request({url: 'plugin:/idea/clickstream/set', name, value, ms});
  },
  // Clickstream: сохранить данные по ключу
  getClickstreamData(name) {
    return this.request({url: 'plugin:/idea/clickstream/get', name});
  },
  // Clickstream: сохранить данные по ключу
  deleteClickstreamData(name) {
    return this.request({url: 'plugin:/idea/clickstream/delete', name});
  },
  toolList(config) {
    return this.request({url: 'plugin:/idea/mcp/toolList', config});
  },
  archLoad({traceId, datasetData, errorMessage}) {
    return this.request({
      url: 'plugin:/idea/arch/load',
      traceId: traceId,
      rawJson: JSON.stringify(datasetData),
      errorMessage: errorMessage
    });
  },
  callTool(config, name, args) {
    return this.request({url: 'plugin:/idea/mcp/callTool', config, name, args});
  },
  s3UploadRequest() {
    return this.request({url: 'plugin:/idea/gateway/s3/upload/request'});
  },
  s3Request({ method = 'GET', targetUrl, headers = {}, textBody = null, multipart = null, responseType = 'text' }) {
    return this.request({
      url: 'plugin:/idea/s3/http',
      method,
      targetUrl,
      headers,
      textBody,
      multipart,
      responseType
    });
  },

  /**
   * Отправка лога частями, если его размер превышает максимальный лимит со стороны java кода
   * @param logRow - строка лога, которая будет разбта на части
   * @private
   */
  _sendLogByPart(logRow) {
    let logId = uuidv4();
    for (let i = 0; i < logRow.message.length; i += javaMessageLimit) {
      const partLog = {
        level: logRow.level,
        tag: logRow.tag,
        message: `part_${logId}: ${logRow.message.slice(i, i + javaMessageLimit)}`,
        errorStack: undefined
      };
      this.request({url: 'plugin:/idea/logs/send', partLog});
    }
    const partLog = {
      level: logRow.level,
      tag: logRow.tag,
      message: undefined,
      errorStack: logRow.errorStack
    };
    this.request({url: 'plugin:/idea/logs/send', partLog});
  }
};

// Ищем окружение плагина

// eslint-disable-next-line no-useless-escape
// const cefQuery = (Object.getOwnPropertyNames(window).filter(item => /^cefQuery\_[0-9]/.test(item)) || [])[0];

const params = new URLSearchParams(document.location.search);
// Пытаемся получить название интерфейсной функции из параметров.
// Если в параметрах ее нет, то берем '%$dochub-api-interface-func%' который
// заботливо должен был подложить плагин заменой.

const fwCefQuery = '%$dochub-api-interface-func%';
let cefQuery = params.get('$dochub-api-interface-func');

// Если в параметрах интерфейсная функция не передана...
if (cefQuery) {
  logger.info(() => 'Нашел интерфейсную функцию в параметрах!');
} else if (!cefQuery && window[fwCefQuery]) {
  cefQuery = fwCefQuery;
  logger.info(() => 'Нашел интерфейсную функцию в коде!');
} else if (!cefQuery && window.localStorage && localStorage.getItem('cefQuery')) {
  logger.info(() => 'Нашел интерфейсную функцию в localStorage!');
  cefQuery = localStorage.getItem('cefQuery');
} else {
  logger.info(() => 'Интерфейсную функцию не нашел.');
}

// eslint-disable-next-line no-console
cefQuery && logger.info(() => `Plugin API function: ${cefQuery}`);

if (cefQuery && window[cefQuery]) {
  PAPI.cefQuery = window[cefQuery];
  window.$PAPI = PAPI;
  window.DocHubIDEACodeExt = {
    rootManifest: 'plugin:/idea/source/$root',
    settings: {
      // Тут нужно определиться или признаком Enerprise является запуск под протоколом http/https или настройка в плагине
      isEnterprise: ['http:', 'https:'].indexOf(window.location.protocol) >= 0,
      render: {
        external: false,
        mode: 'ELK',
        server: ''
      },
      s3CloudUrl: ''
    }
  };
  gateway.initIdeaGateway();

  PAPI.getSettings().then((config) => {
    const supportAPI = process.env.VUE_APP_DOCHUB_IDE_IDEA_API || [];
    if (supportAPI.indexOf(config.api) < 0) {
      const message = `Данная версия плагина имеет версию API [${config.api}]. Требуются версии: ${supportAPI.join(';')}. Возможно необходимо обновить плагин.`;
      logger.error(() => message);
      alert(message);
    }
    // Тут нужно определиться или признаком Enerprise является запуск под протоколом http/https или настройка в плагине
    window.DocHubIDEACodeExt.settings = config;
    logger.info(() => [
        'IDE ENVIRONMENTS:',
        {title: 'config', obj: config}
    ]);
    // Если ide передает дополнительные переменные окружения, сохраняем их разобрав на пары ключ-значение
    if (config.additionalEnv) {
      window.additionalIdeEnv = config.additionalEnv;
    }
    PAPI.onReloadSetting();
  }).catch((e) => {
    alert('Не могу получить конфигурацию плагина.');
    logger.error(() => 'Не могу получить конфигурацию плагина.', e);
  });

  // Оставляем след интерфейсной функции для рефрешей и т.п.
  window.localStorage && localStorage.setItem('cefQuery', cefQuery);
} else {
  logger.info(() => 'Это не плагин jetbrains...');
}

export default cefQuery ? PAPI : false;
