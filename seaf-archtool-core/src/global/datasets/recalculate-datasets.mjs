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
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2025
*/

import generateDatasetErrorDesc from '../helpers/generate-dataset-error-desc.mjs';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

export default async function recalculateDatasets(manifest, driver, peeper) {
    const LOG_TAG = 'datasets-calculate';
    const logger = getLoggerWithTag(LOG_TAG);
    const problems = {
        id: 'dataset--problems',
        title: 'Datasets',
        items: []
    };
    const registeredProblems = new Set();
    let current = 0;
    const datasetsWithError = {};

    const length = Object.keys(manifest.datasets).length;
    for (const key in (manifest.datasets)) {
        logger.debug(() => `Calculating dataset ${key}`);
        if (peeper) {
            peeper.progress = Math.round((current++ + 1) / length * 100);
            peeper.current = key;
        }
        if (registeredProblems.has(manifest.datasets[key].origin)) {
            registeredProblems.add(key);
            problems.items.push({
                uid: key,
                description: `Ориджин ${manifest.datasets[key].origin} не удалось рассчитать из-за ошибки.`
            });
            continue;
        }
        await driver.getData(manifest, { origin: key, source: '({})' }, undefined, undefined, datasetsWithError)
            .catch((err) => {
                if(!datasetsWithError[key]) datasetsWithError[key] = {error: err};
                if (!registeredProblems.has(key)) {
                    registeredProblems.add(key);
                    problems.items.push({
                        uid: key,
                        description: generateDatasetErrorDesc(key, err, datasetsWithError, manifest)
                    });
                }
                logger.error(() => `Dataset ${key} warm up failed`, err);
            });
    }
    if (peeper) {
        peeper.progress = 100;
        peeper.current = 'Done';
    }
    return problems;
}
