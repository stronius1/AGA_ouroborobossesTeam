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
      Saveliy Zaznobin <zaznobins@yandex.ru> - 2025, 2026
      Vladislav Markin, Sber - 2026
*/

import jsonataDriver from '@global/jsonata/driver.mjs';
import queries from '@global/jsonata/queries.mjs';
import jsonataFunctions from '@global/jsonata/functions.mjs';
import env, {Plugins} from '@front/helpers/env';
import requests from '@front/helpers/requests';
import { PerformanceLogger } from '@global/logger/perf-logger.mjs';
import datasets from '@front/helpers/datasets';
import {getLogger, getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import {addPapiSettingUpdateCallbacks} from '@ide/papiLifeCycle';
import { unenvelopeDocument } from '@global/helpers/api/unenvelope.js';

const LOG_TAG = 'front-jsonata-helper';
const logger = getLoggerWithTag(LOG_TAG);

jsonataDriver.getDatasetDriver = () => datasets();
let pluginLogFunc;

if (env.isPlugin(Plugins.idea)) { // window.$PAPI.sendJsonataLog реализован только для jetbrains
    addPapiSettingUpdateCallbacks({
        funcName: 'change isJsonataLogFuncEnable',
        func: () => {
            const isJsonataLogFuncEnable = env.isJsonataLogFuncEnable;
            jsonataDriver.isJsonataLogFuncEnable = isJsonataLogFuncEnable;
            logger.debug(() => `change isJsonataLogFuncEnable = ${isJsonataLogFuncEnable}`);
            pluginLogFunc = (content, tag) => {
                if (isJsonataLogFuncEnable) {
                    let contentToSend = 'null or undefined';
                    if (content) {
                        contentToSend = JSON.stringify(content, null, 2);
                    }
                    window.$PAPI.sendJsonataLog({
                        level: 'info',
                        tag: tag ?? 'log-func-no-tag',
                        message: contentToSend
                    });
                }
            };
        }
    });
}

// Возвращает тело запроса в зависимости от платформы развертывания
function resolveJSONataRequest(ID, params) {
    let result = null;
    if (env.isBackendMode) {
        result = `backend://jsonata/${encodeURIComponent(ID)}`;
        params && (result += `?params=${encodeURIComponent(JSON.stringify(params))}`);
    } else {
        result = queries.makeQuery(queries.QUERIES[ID], params);
    }
    return result;
}

const perfLogger = env.isPerfLoggerEnabled ? new PerformanceLogger(getLogger()) : null;

const queryDriver = {
    driver: jsonataDriver,
    expression(expression, self_, params, isTrace, funcs) {
        return {
            driver: this.driver,
            expOrigin: null,
            onError: null,
            async evaluate(context, def) {
                let result = null;
                try {
                    if (expression.startsWith('backend://')) {
                        const url = new URL(expression);
                        [
                            { field: 'params', value: params},
                            { field: 'subject', value: self_}
                        ].map((param) => {
                            if (!param.value) return;
                            const oldValue = JSON.parse(url.searchParams.get(param.field));
                            const newValue = Object.assign({}, params, oldValue);
                            url.searchParams.set(param.field, JSON.stringify(newValue));
                        });

                        if (env.isEnvelopedRequests && !url.searchParams.has('envelope')) {
                            url.searchParams.set('envelope', 'true');
                        }

                        result = (await requests.request(url)).data;

                        if (env.isEnvelopedRequests) {
                            result = unenvelopeDocument(result);
                        }

                    } else if (!context && env.isBackendMode) {
                        let url = `backend://jsonata/${encodeURIComponent(expression)}`;


                        url += `?params=${encodeURIComponent(JSON.stringify(params || null))}`;
                        url += `&subject=${encodeURIComponent(JSON.stringify(self_ || null))}`;
                        if (env.isEnvelopedRequests) url += '&envelope=true';

                        result = (await requests.request(url)).data;

                        if (env.isEnvelopedRequests) {
                            result = unenvelopeDocument(result);
                        }
                    } else {
                        funcs = funcs || {};
                        funcs.log = funcs.log || pluginLogFunc;
                        !this.expOrigin && (this.expOrigin = this.driver.expression(expression, self_, params, isTrace || env.isTraceJSONata, funcs));
                        result = await this.expOrigin.evaluate(context || window.Vuex.state.manifest || {});
                    }
                } catch (e) {
                    let message = null;
                    if (env.isBackendMode && e?.request?.response) {
                        const content = typeof e?.request?.response === 'object' ? e?.request?.response : JSON.parse(e?.request?.response);
                        message = content.message;
                        logger.error(() => message);
                        if (content.error) {
                            throw content.error;
                        } else {
                            throw e;
                        }
                    } else throw e;
                }
                return result ?? def;
            }
        };
    },

    // ********** ТЕХНОЛОГИИ ***********
    // Сбор информации об использованных технологиях
    collectTechnologies() {
        return resolveJSONataRequest(queries.IDS.TECHNOLOGIES);
    },
    // Карточка технологии
    summaryForTechnology(technology) {
        return resolveJSONataRequest(queries.IDS.TECHNOLOGY, { TECH_ID: technology });
    },

    // ********** СУЩНОСТИ ***********

    // Документы для сущности
    docsForSubject(entity) {
        return resolveJSONataRequest(queries.IDS.DOCUMENTS_FOR_ENTITY, { ENTITY: entity });
    },

    // Сводная JSONSchema по всем кастомным сущностям
    entitiesJSONSchema() {
        return resolveJSONataRequest(queries.IDS.JSONSCEMA_ENTITIES);
    },

    // Сводная JSONSchema по всем кастомным сущностям
    getObject(id) {
        return resolveJSONataRequest(queries.IDS.GET_OBJECT, { OBJECT_ID: id });
    }
};

// Кэш для пользовательских функций
const cacheFunction = {
    moment: null,
    functions: null
};

// Регистрация пользовательских функций
jsonataDriver.customFunctions = () => {
    const state = window.Vuex?.state || {};
    if (!state.moment) return {};
    if (cacheFunction.moment && (cacheFunction.moment === state.moment))
        return cacheFunction.functions;

    const result = (cacheFunction.functions = jsonataFunctions(queryDriver, state?.manifest?.functions || {}, perfLogger));

    cacheFunction.moment = state.moment;
    return result;
};

export default queryDriver;
