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
      R.Piontik <r.piontik@mail.ru> - 2025
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
*/

// Создает исполняющие ручки функций

import ajv from 'ajv';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

const logger = getLoggerWithTag('functions.mjs');
// Генерирует валидатор входных параметров
function makeParamsValidator(handler) {
    // Если параметров нет, то проверять ничего не будем
    if (!handler.profile.params) return null;

    if (!Array.isArray(handler.profile.params))
        throw new Error(`Ошибка описания схемы входных параметров в функции [${handler.id}]!\nПараметры должны описываться массивом.`);

    const schema = {
        type: 'object',
        properties: {},
        required: []
    };
    
    handler.profile.params.map((param, index) => {
        const alias = param.alias || `param${index}`;
        const vParam = Object.assign({}, param);
        delete vParam.alias;
        delete vParam.required;
        schema.properties[alias] = vParam;
        param.required && schema.required.push(alias);
    });

    try {
        const rules = new ajv(
            { allErrors: true,
                logger: {
                    log: (args) => {
                        logger.info(() => JSON.stringify(args));
                    },
                    warn: (args) => {
                        logger.debug(() => JSON.stringify(args));
                    },
                    error: (args) => {
                        logger.debug(() => JSON.stringify(args));
                    }
                } }
        );
        rules.addKeyword({
            keyword: 'callback',
            compile() {
                return (data) => typeof data === 'function';
            }
        });
        rules.addKeyword({
            keyword: 'params',
            compile() {
                return (data) => typeof data === 'function';
            }
        });
        return rules.compile(schema);
    } catch (e) {
        throw new Error(`Ошибка схемы входных параметров в декларации функции [${handler.id}]\n${e.toString()}`);
    }
}

// Генерирует валидатор выходных данных
function makeResultValidator(handler) {
    // Если схемы нет, то проверять ничего не будем
    if (!handler.profile.result) return null;

    const schema = handler.profile.result;

    try {
        const rules = new ajv({ allErrors: true });
        return rules.compile(schema);
    } catch (e) {
        throw new Error(`Ошибка схемы результата в декларации функции [${handler.id}]\n${e.toString()}`);
    }
}

// Генерирует валидаторы входных и выходных данных
function makeValidators(handler) {
    handler.validators = {
        input: makeParamsValidator(handler),
        output: makeResultValidator(handler)
    };
}

// Подготавливает входящие данные и проверяет из структуру
function prepareParams(handler, params) {
    // Если валидатора нет, ничего не проверяем
    const validator = handler.validators.input;
    if (!validator) return null;

    // Готовим параметры на вход
    const result = {
        context: {}
    };
    handler.profile.params.map((param, index) => {
        const alias = param.alias || `param${index}`;
        if (typeof params[index] === 'function') {
            !result.funcs && (result.funcs = {});
            result.funcs[alias] = params[index];
        } else
            result.context[alias] = params[index];
    });

    // Проверяем по схеме
    if (!validator({...result.context, ...result.funcs})) {
        // ajv_localize(validator.errors);
        throw new Error(`Ошибка валидации входных параметров функции [${handler.id}]\n${JSON.stringify(validator.errors, null, 4)}`);
    }

    return result;
}

// Проверяет результат функции по схеме
function prepareResult(handler, result) {
    // Проверяем по схеме
    const validator = handler.validators.output;
    // Если валидатора нет, ничего не проверяем
    if (!validator) return result;

    // Проверяем по схеме
    if (!validator(result)) {
        // ajv_localize(validator.errors);
        throw new Error(`Ошибка валидации результата функции [${handler.id}]\n${JSON.stringify(validator.errors, null, 4)}`);
    }

    return result;
}

export default (queryDriver, functions, performanceLogger) => {
    const result = {};

    for (const funcId in functions) {
        const func = {
            id: funcId,
            profile: functions[funcId],
            executor: null
        };
        result[funcId] = async(...params) => {
            const logger = performanceLogger?.getJsonataLogger(funcId, params);
            logger?.setStart();
            !func.validators && makeValidators(func);
            const input = prepareParams(func, params);  // Подготавливаем параметры и проверяем их на корректность
            let doRebuildQuery = !func.executor;
            if (!doRebuildQuery || input?.funcs || func.funcs) {
                const oldFuncs = Object.assign({}, func.funcs || {});
                for (const funcId in input?.funcs || {}) {
                    if (input.funcs[funcId] !== oldFuncs[funcId]) {
                        doRebuildQuery = true;
                        break;
                    }
                    delete oldFuncs[funcId];
                }
                doRebuildQuery |= Object.keys(oldFuncs).length;
            }
            if (doRebuildQuery) {
                func.executor = queryDriver.expression(
                    func.profile?.code || 'undefined',
                    undefined,
                    undefined,
                    undefined,
                    input?.funcs
                );
            }
            const result = await func.executor.evaluate(input?.context);
            func.funcs = input?.funcs;
            const output = prepareResult(func, result);
            logger?.setEnd(output);
            return output;
        };
    }

    return result;
};
