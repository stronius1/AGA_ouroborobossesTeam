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
      Sergeev Viktor, Sber - 2026

  Contributors:
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2026
*/

import consts from '@front/consts.js';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import userRightStore from '@front/store/userRightStore.js';

const logger = getLoggerWithTag('f/h/orgCtxOnStartPageHelper');


/**
 * Обработка параметра orgctx
 * 1. Ищем параметр в url текущей страницы или в странице с которой перешли или берем из прав пользователя
 * 2. Сохраняем orgCtx в userRightStore и устанавливаем на страницу если еще нету
 */
export function processingOrgCtx() {
    let orgCtx = findOrgCtxInUrl();
    logger.debug(() => `found OrgCtx in url with value '${orgCtx}'`);
    if (!orgCtx) {
        // Если в адресной строке нет контекста, то берем первый из доступных т.к. на этот момент пользователь еще ничего не выбрал
        orgCtx = userRightStore.getFirstUserCtxAlias();
        logger.debug(() => `OrgCtx in url was null or undefined, try get first from userStore, receive '${orgCtx}'`);
    }
    if (orgCtx) {
        addOrgCtxInUrl(orgCtx);
        userRightStore.setCurrentCtx(orgCtx);
    } else {
        logger.info(() => 'not found ctx in url or user right store');
    }
}

/**
 * сохраняем контекст в url (_sfa-orgctx) при переходах по роутам если он есть
 * @param to - целевая страница для перехода
 * @param from - исходная страница, с которой произошел переход
 */
export function orgCtxRoutHandler(to, from) {
    const fromContext = from.query[consts.roleModelV2.urlAliasParamName];
    const toContext = to.query[consts.roleModelV2.urlAliasParamName];

    if (fromContext !== toContext) { // если _sfa-orgctx на целевой странице отличается от исходной страницы
        if (fromContext) { // и на исходной странице есть _sfa-orgctx
            to.query[consts.roleModelV2.urlAliasParamName] = fromContext; // тогда переносим его на целевую страницу
            if (toContext) { // при этом если на целевой странице тоже указан _sfa-orgctx
                to.query[consts.roleModelV2.urlOriginAliasParamName] = toContext; // то сохраняем его в другом атрибуте (в планах возможно показать уведомление о разных контекстах)
            }
        } else { // если на исходной странице контекста нет, но он есть на целевой (потому что они не равны)
            from.query[consts.roleModelV2.urlAliasParamName] = toContext; // то исходной проставим целевой (чтобы не попасть в вечный цикл)
        }

        if (fromContext !== toContext) {
            return {
                path: to.path,
                query: to.query,
                params: to.params
            };
        }
    }
}

/**
 * Ищем _sfa-orgctx
 * Сначала проверяем может он есть в url который открыт.
 * Если нет, тогда смотрим document.referrer - страницу с которой перешли, контекст в этом случае пробрасываем на текущую вкладку
 * Если и в document.referrer нет, тогда ничего не делаем
 *
 * @returns {string,null} - вернем строку со значением найденного контекста или null
 */
function findOrgCtxInUrl() {
    let resultCtx = null;
    const currentLocation = new URL(window.location.href);
    const currentLocationParams = new URLSearchParams(currentLocation.search);
    const currentLocationCtx = currentLocationParams.get(consts.roleModelV2.urlAliasParamName);
    if (currentLocationCtx) {
        resultCtx = currentLocationCtx;
        logger.debug(() => `seaf ctx '${currentLocationCtx}' found in page url`);
    } else if(document.referrer) {
        logger.debug(() => `seaf ctx not found in page url, try search in referrer: ${document.referrer}`);
        const referrerUrl = new URL(document.referrer);
        const referrerParams = new URLSearchParams(referrerUrl.search);
        const referrerCtx = referrerParams.get(consts.roleModelV2.urlAliasParamName);
        if (referrerCtx) {
            resultCtx = referrerCtx;
            logger.debug(() => `seaf ctx '${referrerCtx}' found in referrer`);
        } else {
            logger.debug(() => [
                'seaf ctx not found in referrer',
                {title: 'document.referrer', obj: document.referrer}
            ]);
        }
    } else {
        logger.debug(() => [
            'seaf ctx not found in page url and document.referrer is null or empty',
            {title: 'document.referrer', obj: document.referrer}
        ]);
    }

    return resultCtx;
}

/**
 * Добавляем orgCtx в url через pushState
 * @param orgCtx
 */
function addOrgCtxInUrl(orgCtx) {
    if (!orgCtx) {
        logger.warn(() => [
            'addOrgCtxInUrl receive null or undefined "orgCtx" param, cannot set in url',
            {title: 'document.referrer', obj: document.referrer}
        ]);
        return;
    }
    const currentLocation = window.location;
    const searchParams  = new URLSearchParams(currentLocation.search);
    const currentLocationCtx = searchParams.get(consts.roleModelV2.urlAliasParamName);
    if (currentLocationCtx !== orgCtx) { // устанавливаем orgctx в url если его нет или он отличается
        searchParams.append(consts.roleModelV2.urlAliasParamName, orgCtx);
        window.Router.push({
            path: currentLocation.pathname,
            query: Object.fromEntries(searchParams) // тут пока не допускаются дубли параметров, может быть проблемой, но пока такой фикс
        });
    }
}
