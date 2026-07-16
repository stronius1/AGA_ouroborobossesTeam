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

import queries from '../../global/jsonata/queries.mjs';
import { buildUserMenu } from '@global/manifest/services/menu-builder.mjs';
import datasets from '../helpers/datasets.mjs';
import { isRolesMode, retrieveRolesManifest } from '../utils/roles.mjs';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import {getCachePrefixWithDomain} from '@back/helpers/cachePrefixByDomain.mjs';

const logger = getLoggerWithTag('menu-warmup');

export default async function(storage, cache) {
    logger.trace(() => 'User menu cache warm up started');
    const query = `(${queries.IDS.USER_MENU})`;
    const cachePrefix = getCachePrefixWithDomain(storage);
    if (!isRolesMode()) {
        await cache.pullFromDataCache(cachePrefix, JSON.stringify({ query }), async() => {
            return await buildUserMenu(storage.manifest, datasets(storage).jsonataDriver);
        }).catch(() => {
            logger.error(() => 'User menu warm up failed');
        });
    } else {
        const roleManifest = retrieveRolesManifest();
        for(const role in roleManifest?.roles) {
            await cache.pullFromDataCache(cachePrefix, JSON.stringify({ query, ruleId: role }), async() => {
                return await buildUserMenu(storage.manifests[role], datasets(storage).jsonataDriver);
            }).catch(() => {
                logger.error( () => `User menu warm up failed for role ${role}`);
            });
        }
    }
    logger.trace(() => 'User menu cache warm up finished');
}
