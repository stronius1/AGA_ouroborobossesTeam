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
*/

import generateDatasetErrorDesc from '@global/helpers/generate-dataset-error-desc.mjs';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import objectHash from 'object-hash';
import requestBitBucketHash from '@back/utils/get-bitbucket-commit-sha.mjs';
import {isRolesMode} from '@back/utils/roles.mjs';
import { v4 as uuidv4 } from 'uuid';

const LOG_TAG = 'datasets-calculate';
const logger = getLoggerWithTag(LOG_TAG);

function datasetOriginsAsArray(datasetDefinition) {
    const origin = datasetDefinition.origin;
    if (typeof origin === 'object') {
        return Object.values(origin);
    } else {
        return [origin];
    }
}

export async function calcNewDatasetsChecksum(storage) {
    const checksums = {};
    const manifest = isRolesMode() ? storage.manifests.origin : storage.manifest;
    // На данный момент собираем чексуммы только для BB репозиториев.
    const checksumPromises = Object.entries(manifest.datasets).map(async([key, datasetRec]) => {
        let hash = null;
        if (typeof datasetRec.source === 'string' && datasetRec.source.startsWith('bitbucket:')) {
            hash = await requestBitBucketHash(datasetRec.source).catch((err) => {
                logger.error(() => `Не удалось установить коммит для датасета ${key}`, err);
                return null;
            });
        }
        checksums[key] = { hash };
    });
    await Promise.all(checksumPromises);
    return checksums;
}

export default async function recalculateDatasetsBackend(manifest, driver, oldHashes, newHashes, copyDatasetFromOldCache) {
    logger.debug(() => 'Datasets warm up started');
    const problems = {
        id: 'dataset--problems',
        title: 'Datasets',
        items: []
    };
    const registeredProblems = new Set();
    let recalculateCounter = 0;
    const datasetsWithError = {};

    function registerProblem(datasetKey, description) {
        registeredProblems.add(datasetKey);
        problems.items.push({
            uid: datasetKey,
            description: description
        });
    }

    async function calcDataset(key) {
        recalculateCounter++;
        return await driver.getData(manifest, { origin: key, source: '($)' }, undefined, undefined, datasetsWithError)
            .catch((err) => {
                if(!datasetsWithError[key]) {
                    datasetsWithError[key] = {error: err};
                }
                if (!registeredProblems.has(key)) {
                    registerProblem(key, generateDatasetErrorDesc(key, err, datasetsWithError, manifest));
                }
                logger.error(() => `Dataset ${key} warm up failed`, err);
            });
    }
    
    async function handleDataset(checksums, key) {
        // Если записывали чексумму, значит это BB репозиторий. Проверяем, изменился ли SHA.
        if (checksums[key]?.hash && checksums[key].hash === oldHashes?.[key]?.hash && copyDatasetFromOldCache) {
            copyDatasetFromOldCache(key);
            return;
        }            

        const dataset = await calcDataset(key);
        if (!checksums[key]?.hash) {
            if (!checksums[key]) checksums[key] = {};
            const datasetString = JSON.stringify(dataset);
            try {
                checksums[key].hash = objectHash.MD5(datasetString ?? '');
            } catch (err) {
                checksums[key].hash = uuidv4();
                throw err;
            }
        }
    }
    for (const key of Object.keys(manifest.datasets)) {
        logger.debug(() => `Processing dataset ${key}`);

        const datasetDefinition = manifest.datasets[key];
        const datasetOrigins = datasetOriginsAsArray(datasetDefinition);
        const originsWithError = [];
        for (const origin of datasetOrigins) {
            if (registeredProblems.has(origin)) {
                originsWithError.push(origin);
            }
        }
        if (originsWithError.length !== 0) {
            if(!datasetsWithError[key]) {
                datasetsWithError[key] = {error: {message: 'Ошибки в датасетах, указанных в origin'}};
            }
            registerProblem(key, generateDatasetErrorDesc(key, 'Ошибки в датасетах, указанных в origin', datasetsWithError, manifest));
            continue;
        }
        try {
            await handleDataset(newHashes, key);
        } catch (err) {
            let customMessage = '';
            if (err.name === 'RangeError') {
                customMessage = 'The calculated dataset result is too large to process (RangeError)';
            }
            const errorUuid = uuidv4();
            logger.error(() => `${errorUuid}: Failed handleDataset of dataset: ${key}. ${customMessage}`, err);
            registerProblem(key, `Датасет ${key} не удалось рассчитать из-за ошибки. uuid = ${errorUuid}`);
        }
    }

    logger.debug(() => `Пересчитано ${recalculateCounter} датасетов из ${Object.keys(manifest.datasets).length}.`);

    return problems;
}
