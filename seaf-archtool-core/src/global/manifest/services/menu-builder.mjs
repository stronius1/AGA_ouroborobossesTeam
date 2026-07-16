/*
  Copyright (C) 2023 Sber

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
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber

  Contributors:
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
*/

import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

const LOG_TAG = 'menu-builder';
const logger = getLoggerWithTag(LOG_TAG);

const DEF_ORDER = 10000;
const JSONATA = {
    'title': 'JSONata',
    'route': '/devtool',
    'icon': 'mdi-card-text-outline',
    'location': 'devtool',
    'order': DEF_ORDER
};
const SEARCH = {
    'title': 'Поиск',
    'route': '/search',
    'icon': 'mdi-magnify',
    'location': 'Поиск',
    'order': DEF_ORDER - 1
};
const PROBLEMS = {
    'title': 'Проблемы',
    'location': 'Проблемы',
    'route': '/problems',
    'icon': 'mdi-alert-circle-outline',
    'order': DEF_ORDER
};

const isUrl = new RegExp('^[a-zA-Z]*\\:.*$', 'i');


export async function buildUserMenu(manifest, driver) {
    if (!manifest?.entities) return [];
    const output = [];
    for (const [key, entity] of Object.entries(manifest.entities)) {
        if (!entity.menu) continue;
        const query = `($manifest := $; entities."${key}".(($exists(menu.source) ? $parsesource(menu) : $eval(menu, $manifest)).{"route": link, "location": location, "icon": icon, "order": order}))`;
        try {
            const ele = await driver.expression(query).evaluate(manifest);
            if (!ele) {
                logger.info(() => `Menu query for entity ${key} didn't return anything`);
                continue;
            }
            if (Array.isArray(ele)) {
                for (const item of ele) {
                    prepareElement(item);
                    output.push(item);
                }
            } else {
                prepareElement(ele);
                output.push(ele);
            }
        } catch (e) {
            logger.error(() => `Failed to build user menu for entity ${key}: ${JSON.stringify(e)}`);
            continue;
        }
    }

    output.sort((a, b) => a.order - b.order || a.location.localeCompare(b.location));
    output.push(SEARCH, PROBLEMS, JSONATA);
    return output;
}

function prepareElement(ele) {
    ele.route = ele.route ? (
        isUrl.test(ele.route) ? ele.route
        : (ele.route.startsWith('/') ? ele.route : '/' + ele.route )
    ) : undefined;
    ele.title = ele.location?.slice(ele.location.lastIndexOf('/') + 1);
    ele.order = ele.order ?? DEF_ORDER;
}
