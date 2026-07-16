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
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025, 2026
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
*/

import jsonata from 'jsonata';
import ajv from 'ajv';
import addFormats from 'ajv-formats';
import source from '../datasets/source.mjs';
import { BaseEntities } from '../../global/entities/entities.mjs';
import { PerformanceLogger } from '../logger/perf-logger.mjs';
import {getLogger, getLoggerWithTag} from '@global/logger/v2/logger.mjs';

const LOG_TAG = 'jsonata-driver';
const logger = getLoggerWithTag(LOG_TAG);
const loggerWithoutTag = getLogger();

// Расширенные функции JSONata
function wcard(id, template) {
    if (!id || !template) return false;
    const tmlStruct = template.split('.');
    let items = [];
    for (let i = 0; i < tmlStruct.length; i++) {
        const pice = tmlStruct[i];
        if (pice === '**') {
            items.push('.*$');
            break;
        } else if (pice === '*') {
            items.push('[^\\.]*');
        } else items.push(pice);
    }

    const isOk = new RegExp(`^${items.join('\\.')}$`);

    return isOk.test(id);
}

async function parseSource(source) {
  return await this.getDatasetDriver()?.getData(this.manifest, source);
}

function mergeDeep(sources) {
    function mergeDeep(target, sources) {
        function isObject(item) {
            return (item && typeof item === 'object' && !Array.isArray(item));
        }

        if (!sources.length) return target;
        const source = sources.shift();

        if (isObject(target) && isObject(source)) {
            for (const key in source) {
                if (isObject(source[key])) {
                    if (!target[key]) Object.assign(target, { [key]: {} });
                    mergeDeep(target[key], [source[key]]);
                } else {
                    Object.assign(target, { [key]: source[key] });
                }
            }
        }
        return mergeDeep(target, sources);
    }
    return mergeDeep({}, sources);
}

let jsonValidatorLog = getLoggerWithTag('jsonValidator');
function jsonSchema(schema) {
    const rules = new ajv(
        { allErrors: true,
            unicodeRegExp: false,
            allowUnionTypes: true,
            verbose: true,
            logger: {
                log: (args) => {
                    jsonValidatorLog.info(() => JSON.stringify(args));
                },
                warn: (args) => {
                    jsonValidatorLog.debug(() => JSON.stringify(args));
                },
                error: (args) => {
                    jsonValidatorLog.debug(() => JSON.stringify(args));
                }
            }
        });
    addFormats(rules);
    rules.addKeyword({
        keyword: '$rels'
    });
    const validator = rules.compile(schema);
    return (data) => {
        const isOk = validator(data);
        if (isOk) return true;

        return validator.errors
            .filter(err => err.keyword !== 'if')
            .map((err) => {
                // убираем из ответа verbose инфу, т.к. она не нужна
                let attrInfo = {};
                try {
                    attrInfo = __getAttrInfoByError(err, schema);
                } catch (e) {
                    // TODO: вернуть лог с уровнем дебаг после доработки ERA-1219,
                    //      пока игнорируем, отработает jsonata функция поиска
                    // console.error(e);
                }
                return {
                    attrInfo: attrInfo,
                    instancePath: err.instancePath,
                    schemaPath: err.schemaPath,
                    keyword: err.keyword,
                    params: err.params,
                    allowedValues: err.allowedValues,
                    message: err.message
                };
            }
        );
    };
}

/**
 * Метод собирает подробную информацию об ошибке
 * 1. Если ошибка в атрибуте со schemaPath, который начинается на $rels то необходимо найти реальную схему атрибута,
 *      т.к. rels перечисление создается в райнтайме, по сущностям пользователя и по факту это ограничение типа enum
 * 2. Для ошибок типа required в самой ошибке содержится схема всего объекта, чей атрибут пропущен, там и ищем описание параметра
 * 3. Для остальных случаев берем из parentSchema данные
 *
 * @param err - ошибка ajv валидатора
 * @param schema - схема использованная для валидации
 * @returns Объект описывающий ошибку
 *
 * @private
 */
function __getAttrInfoByError(err, schema) {
    let currentSchema;
    let title;
    let type;
    let instancePathSplit = !err.instancePath ? [] : err.instancePath.replace(/^\//, '').split('/');
    // глубина массива, используется при формировании attrName, чтобы собрать название атрибута из имени массива и индексов
    let arrayDepth = 0;

    if (err.keyword === 'required') { // если ошибка в required, то в parentSchema схема всего объекта с ошибкой, а не атрибута
        let propertyName = err.params.missingProperty;
        let propertyDesc = err.parentSchema?.properties?.[propertyName];
        title = propertyDesc?.title;
        type = propertyDesc?.type;
    } else { // иначе в parentSchema описание атрибута
        title = err.parentSchema?.title;
        type = err.parentSchema?.type;
    }

    if ((!title || !type) && instancePathSplit.length > 0) {
        //если не нашли тип или заголовок и есть путь для поиска в схеме, то ищем в схеме
        let segment;
        currentSchema = schema;
        for (segment of instancePathSplit) {
            if (segment === '') {
                continue;
            }
            if (currentSchema.type === 'array') {
                // увеличиваем глубину если в пути наткнулись на массив
                arrayDepth++;
            } else {
                // обнуляем глубину массива если наткнулись на обычный элемент, не массив
                arrayDepth = 0;
            }

            if (currentSchema?.properties?.[segment]) {
                currentSchema = currentSchema.properties[segment];
            } else if (currentSchema?.patternProperties) {
                const matchingPattern = Object.keys(currentSchema.patternProperties).find(pattern =>
                    new RegExp(pattern).test(segment)
                );
                if (matchingPattern) {
                    currentSchema = currentSchema.patternProperties[matchingPattern];
                } else {
                    currentSchema = null;
                    break;
                }
            } else if (currentSchema.allOf || currentSchema.oneOf || currentSchema.anyOf) {
                const merged = [
                    ...safeArray(currentSchema.allOf),
                    ...safeArray(currentSchema.oneOf),
                    ...safeArray(currentSchema.anyOf)
                ];
                // пробуем найти описание атрибута в properties какого-нибудь из allOf/oneOf/anyOf
                let segmentInProperties = merged.find(el => el?.properties?.[segment]);
                if (segmentInProperties) {
                    currentSchema = segmentInProperties.properties[segment];
                } else {
                    // если в properties нету, и есть $ref ссылки, поищем в них
                    currentSchema = merged
                        .filter(el => el.$ref)
                        .map(el => el.$ref)
                        .map(el => el.replace('#/$defs/', ''))
                        .filter(el => Object.hasOwn(schema.$defs[el].properties, segment))
                        .map(el => schema.$defs[el].properties[segment])
                        .filter(el => el)[0];
                }
            } else if (currentSchema.type === 'array' && currentSchema.items.$ref) {
                // т.к. текущая схема это массив ссылающийся на другой элемент, ничего не делаем
            } else if (currentSchema.type === 'array' && currentSchema.items.type === 'array') {
                if (!currentSchema.items.title) {
                    // если у вложенного массива нет заголовка, то протаскиваем его от родительского массива
                    currentSchema.items.title = currentSchema.title;
                }
                // т.к. текущая схема это массив ссылающийся на другой массив то переходим в схему items
                currentSchema = currentSchema.items;
            } else {
                currentSchema = null;
                break;
            }
        }
        if (currentSchema) {
            title = currentSchema['title'];
            type = currentSchema['type'];
        }
    }

    let currentValue;
    let attrName;
    if (err.keyword === 'required') {
        attrName = err.params.missingProperty;
        currentValue = err.data[attrName];
    } else {
        attrName = instancePathSplit.at(-arrayDepth - 1);
        for (let i = arrayDepth; i > 0; i--) {
            attrName += `[${instancePathSplit.at(-i)}]`;
        }
        currentValue = err.data;
    }
    if (!title) {
        // если заголовок атрибута в конце парсинга не найден, то попробуем добавить атрибут "комментарий", так договорились
        title = err.parentSchema.$comment;
    }
    // если attrName есть (не null/undefined/не пустая строка), тогда срезаем пробелы по краям
    if (attrName) {
        attrName = attrName.trim();
    } else {
        attrName = undefined;
    }
    return {
        title: title,
        type: type,
        currentValue: currentValue,
        name: attrName
    };
}

const safeArray = (arr) => Array.isArray(arr) ? arr : [];

async function manifestSchema() {
    return BaseEntities.getSchema();
}

function sourceType(content) {
    return source.type(content);
}

// Функция для переопределения встроенной $lookup()
// должна допускать null в качестве ключа, и возвращать null в этом случае.
function lookup(source, key) {
    // обрабатываем ситуацию, когда функция была вызвана в виде $obj.$lookup('key');
    if (key === undefined && (typeof source === 'string' || source === null)) {
        key = source;
        source = this.input;
    }

    if (key === null) return null;

    if (Array.isArray(source)) {
        const output = [];
        for (let i = 0; i < source.length; i++) {
            let value = lookup(source[i], key);
            if (value !== undefined) {
                if (Array.isArray(value)) {
                    output.push(...value);
                } else output.push(value);
            }
        }
        return output;
    } else if (typeof source === 'object' && !source._jsonata_function && !source._jsonata_lambda) return source[key];
}

const coreFunctions = {
    manifestschema: manifestSchema,
    sourcetype: sourceType,
    wcard: wcard,
    mergedeep: mergeDeep,
    jsonschema: jsonSchema
};

/**
 * Метод для добавления функции со стороны frontend или backend. Когда одна функция работает по-разному в этих режимах
 * Важно соблюдать корректность поведения функции в обоих режимах, чтобы поведение было ожидаемо
 * @param name - название функции
 * @param func - тело функция
 */
export function appendCoreFunctions(name, func) {
    if (coreFunctions[name]) {
        logger.error(() =>`WARN: some add func '${name}' twice, check source code by func name`);
    }
    coreFunctions[name] = func;
}

function getDatasetDriver() {
  logger.error(() => 'ERROR: Cant get dataset driver from jsonata driver core');
}

async function tryExecute(func, args) {
    if (typeof func === 'function') {
        try {
            const result = await func.apply(this, args);
            return { success: true, result };
        } catch (e) {
            logger.error(() => `tryExecute error: ${e.message}`, e);
            return { success: false, result: null, error: e.message };
        }
    } else {
        const message = `tryExecute error: First argument of tryExecute must be a function. Received ${typeof func} instead.`;
        logger.error(() => message);
        return { success: false, result: null, error: message };
    }
}

const PERF_LOG_ENABLE = process.env.VUE_APP_DOCHUB_PERF_LOGGER_ENABLE?.toLowerCase() === 'on';
export default {
    // Функция должна возвращать коллекцию пользовательских функций JSONata
    customFunctions: null,
    logger: logger,
    performanceLogger: PERF_LOG_ENABLE ? new PerformanceLogger(loggerWithoutTag) : null,
    isJsonataLogFuncEnable: process.env.VUE_APP_DOCHUB_JSONATA_LOG_FUNC_ENABLE?.toLowerCase() !== 'off',
    getDatasetDriver,
    // Создает объект запроса JSONata
    //  expression - JSONata выражение
    //  self    - объект, который вызывает запрос (доступен по $self в запросе)
    //  params  - параметры передающиеся в запрос
    //  isTrace - признак необходимости проанализировать выполнение запроса.
    //          Если true, то в объекте запроса, после его выполнения, появится поле "trace"
    //  funcs - кастомные функции, регистрируемые в JSONata
    expression(expression, self_, params, isTrace, funcs) {
        const obj = {
            expression,
            customFunctions: this.customFunctions ? this.customFunctions() : {},
            core: null,
            onError: null,  // Событие ошибки выполнения запроса
            store: {},      // Хранилище вспомогательных переменных для запросов
            logger: this.logger,    // Логгер трассировки запросов
            performanceLogger: this.performanceLogger,   // Логгер производительности функций
            getDatasetDriver: this.getDatasetDriver,
            isJsonataLogFuncEnable: this.isJsonataLogFuncEnable,
            // Исполняет запрос
            //  context - контекст исполнения запроса
            async evaluate(context) {
                try {
                    const performanceLogger = this.performanceLogger;
                    if (!this.core) {
                        this.core = jsonata(this.expression);
                        this.core.assign('self', self_);
                        this.core.assign('params', params);
                        this.manifest = context;
                        this.core.registerFunction('lookup', lookup);
                        this.core.registerFunction('parsesource', parseSource.bind(this));
                        this.core.registerFunction('tryexecute', tryExecute.bind(this));
                        for (const functionId in coreFunctions) {
                            this.core.registerFunction(functionId, function() {
                                if (!PERF_LOG_ENABLE) return coreFunctions[functionId](...arguments);
                                const jsonataPerfLogger = performanceLogger?.getJsonataLogger(functionId, arguments);
                                jsonataPerfLogger?.setStart();
                                const output = coreFunctions[functionId](...arguments);
                                jsonataPerfLogger?.setEnd(output);
                                return output;
                            });
                        }
                        for (const functionId in this.customFunctions) {
                            this.core.registerFunction(functionId, this.customFunctions[functionId]);
                        }
                        if (!funcs?.log) {
                            this.core.registerFunction('log', (content, tag) => {
                                if(this.isJsonataLogFuncEnable) {
                                    loggerWithoutTag.info(tag ?? 'log-func-no-tag', () => JSON.stringify(content, null, 2));
                                }
                            });
                        }
                        this.core.registerFunction('set', (key, data) => {
                            return obj.store[key] = data;
                        });
                        this.core.registerFunction('get', (key) => {
                            return obj.store[key];
                        });
                        for (const name in funcs || {}) {
                            if (funcs[name]) this.core.registerFunction(name, funcs[name]);
                        }
                    }

                    return new Promise((success, reject) => {
                        obj.trace = {
                            start: (new Date()).getTime(),
                            end: null
                        };
                        const doStat = (result) => {
                            obj.trace.end = (new Date()).getTime();
                            obj.trace.exposition = this.trace.end - this.trace.start;
                            logger.trace(() => [
                                `JSONata tracer expression (${obj.trace.exposition / 1000} seconds)`,
                                {title: 'Statistics', obj: obj.trace},
                                {title: 'Query', obj: obj.expression},
                                result ? {title: 'Result', obj: result} : null
                            ]);
                        };
                        this.core.evaluate(context)
                            .then((result) => {
                                isTrace && doStat(result);
                                success(result);
                            })
                            .catch((error) => {
                                isTrace && doStat();
                                if (reject) reject(error);
                            });
                    });

                } catch (e) {
                    logger.error(() => [
                        'JSONata error:',
                        {title: 'Error', obj: e.message},
                        {title: 'Expression', obj: this.expression.slice(0, e.position) + '%c' + this.expression.slice(e.position)}
                    ], e);
                    throw e;
                }
            }
        };
        return obj;
    }
};
