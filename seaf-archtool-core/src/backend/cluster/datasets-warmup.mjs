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
      Vladislav Markin <markinvy@yandex.ru>, Sber

  Contributors:
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2024
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
*/

import datasets from '../helpers/datasets.mjs';
import recalculateDatasets from '@back/helpers/recalculate-datasets.mjs';
import {isRolesMode} from '@back/utils/roles.mjs';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import {getCachePrefixWithDomain, getDsChecksumPrefixWithDomain} from '@back/helpers/cachePrefixByDomain.mjs';

const LOG_TAG = 'datasets-warmup';
const UPDATER_PREFIX = 'tmp-dataset-updater-prefix';
const logger = getLoggerWithTag(LOG_TAG);

export default async function(storage, cache, isCluster, oldManifestMeta, newChecksums) {
    logger.info(() => 'Datasets cache warm up started');
    let oldManifestHash = oldManifestMeta?.manifestHash;
    let oldManifestCachePrefix = getCachePrefixWithDomain(storage, oldManifestHash);
    let oldDatasetHash = oldManifestMeta?.datasetHash;
    let oldChecksums;
    if (oldDatasetHash) {
        const oldDatasetsChecksumCachePrefix = getDsChecksumPrefixWithDomain(storage, oldManifestHash);
        oldChecksums = await cache.pullFromDataCache(oldDatasetsChecksumCachePrefix, oldDatasetHash);
    }
    let cachePrefixTmp = UPDATER_PREFIX;
    if (storage.permission) {
        cachePrefixTmp = `${UPDATER_PREFIX}.${storage.permission}`;
    }

    async function copyDatasetFromOldCache(key) {
        const cacheKey = `{"path":"/datasets/${key}"}`;
        await cache.updateInDataCache(cachePrefixTmp, cacheKey, async() => {
            await cache.pullFromDataCache(oldManifestCachePrefix, cacheKey);
        }).then(() => {
            logger.debug(() => `Копирование датасета ${key} из старого кеша завершено`);
        });
    }

    const datasetUpdater = datasets(storage, null, cachePrefixTmp);
    const problems = await recalculateDatasets(
        isRolesMode() ? storage.manifests.origin : storage.manifest,
        datasetUpdater,
        oldChecksums,
        newChecksums,
        copyDatasetFromOldCache
    );

    const newManifestCachePrefix = getCachePrefixWithDomain(storage);
    if (!isCluster || oldManifestHash !== storage.hash) {
        oldManifestHash && logger.debug(() => 'Зафиксировано изменение в манифесте или датасетах.');
        const promises = [];
        for (const key of Object.keys(newChecksums)) {
            const cacheKey = `{"path":"/datasets/${key}"}`;
            promises.push(cache.moveInDataCache(cachePrefixTmp, cacheKey, newManifestCachePrefix, cacheKey));
        }
        Promise.allSettled(promises);
    } else {
        logger.debug(() => 'Не зафиксировано изменений в манифесте или датасетах.');
    }

    if (problems.items.length > 0) storage.problems.push(problems);

    logger.info(() => 'Datasets cache warm up finished');
}
