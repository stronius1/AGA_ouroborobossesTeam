/*
  Copyright (C) 2026 Sber

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
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber

  Contributors:
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber
*/

/**
 * При миграции на новую версию url потребовалось сохранить совместимость со старыми адресами на время.
 * Время ограничили 6-12 мес начиная с марта 2026 года.
 * В некоторых местах сделаны разные решения, чтобы один контроллер обрабатывал обе версии.
 * После отказа от старой версии апи из можно будет удалить. Как ориентир можно взять коммит с доработокой, в которой
 * написана эта документация
 *
 * reqWithoutManifestV2 - содержит список исключений, для которых в api v2 НЕ НУЖЕН манифест. По дефолту он нужен всем
 *                      чей адрес начинается на seaf-core/api кроме исключений.
 * reqWithManifestV1 - список адресов v1 которым НУЖЕН манифест. Т.к. апи дополняться не будет, есть возможность его зафиксировать
 *
 * Метод noNeedManifest проверяет, что манифест не нужен ни 1 ни 2 версии апи. Если кому-то нужен вернет true
 * Для версии 1 манифест нужен всем запросам, чей адрес начинается из списка reqWithManifestV1
 * Для версии 2 манифест нужен всем, чем адрес начинается на /seaf-core/api за исключением списка reqWithoutManifestV2
 */

import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

const logger = getLoggerWithTag('/b/h/manifestNeedChecker');

const reqWithoutManifestV2 = [
    '/seaf-core/api/core/user/rights',
    '/seaf-core/api/core/about-alias',
    '/seaf-core/api/logger',
    '/seaf-core/api/core/storage/reload',
    '/seaf-core/api/title',
    '/seaf-core/api/env-config',
    '/seaf-core/api/smartants'
];

/**
 * Список адресов первой версии апи, для которых манифест обязателен. Т.к. новые сервисы должны быть по новому формату
 * с префиксом /seaf-core/api, то этот список не должен меняться
 */
const reqWithManifestV1 = [
    '/core/storage', // все запросы к jsonata и datasets не указываю конкретные адреса т.к. есть storage.mjs в котором путь указан как core/storage/:hash т.е. любой путь не обработанный ранее
    '/entities', // entity.mjs
    '/new/chat', // gigachat.ts
    '/manifest-mutation' // manifestMutator.mjs
];
const reqWithManifestV1Exclude = [
    '/core/storage/reload' // перезагрузка не требует авторизации
];

/**
 * Проверяет, требуется ли манифест для обработки указанного HTTP запроса
 */
export function noNeedManifest(req) {
    return noNeedManifestV2(req) && noNeedManifestV1(req);
}

/**
 * Проверяет, требуется ли манифест для обработки указанного HTTP запроса для запросов версии 1
 *
 * Функция определяет, нужно ли обрабатывать запрос с использованием манифеста
 * на основе предопределенного списка URL-префиксов, которым требует манифест
 *
 * @param {Object} req - Объект запроса
 * @returns {boolean} - Возвращает true, если запрос НЕ требует манифеста (не найден в списке)
 */
function noNeedManifestV1(req) {
    let result = !reqWithManifestV1.some(prefix => req.path.startsWith(prefix)) || // если путь в обязательных не найден, то манифест не нужен
        reqWithManifestV1Exclude.some(prefix => req.path.startsWith(prefix)); // но есть некоторые исключения
    logger.trace(() => [
        'noNeedManifest check v1',
        {title: 'req.path', obj: req.path},
        {title: 'reqWithManifestV1', obj: reqWithManifestV1},
        {title: 'result check', obj: result}
    ]);
    return result;
}


/**
 * Проверяет, требуется ли манифест для обработки указанного HTTP запроса для запросов версии 2
 *
 * Функция определяет, нужно ли обрабатывать запрос с использованием манифеста
 * на основе наличия префикса /seaf-core/api кроме исключений
 *
 * @param {Object} req - Объект запроса
 * @returns {boolean} - Возвращает true, если запрос НЕ требует манифеста
 */
function noNeedManifestV2(req) {
    let result = !req.path.startsWith('/seaf-core/api') || reqWithoutManifestV2.some(prefix => req.path.startsWith(prefix));
    logger.trace(() => [
        'noNeedManifest check v2',
        {title: 'req.path', obj: req.path},
        {title: 'reqWithoutManifest', obj: reqWithoutManifestV2},
        {title: 'result check', obj: result}
    ]);
    return result;
}
