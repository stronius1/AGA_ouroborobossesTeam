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

  Contributors:
      Marat Niyazmatov, Sber - 2026
*/

import { getSearchEntityConfig } from './search-config.mjs';
import { getLoggerWithTag } from '@global/logger/v2/logger.mjs';

const LOG_TAG = 'search-data';
const logger = getLoggerWithTag(LOG_TAG);

/**
 * Извлекает map объектов сущности из озера или результата датасета.
 * Датасет возвращает структуру, зеркалирующую озеро: { [entityId]: { objectKey: objectData } }.
 * Если срез отсутствует или пуст — возвращает {} (поиск по сущности даст 0 результатов).
 *
 * @param {object} source - manifest или результат releaseData
 * @param {string} entityId
 * @returns {Record<string, object>}
 */
export function extractEntityObjects(source, entityId) {
    if (!source || typeof source !== 'object') {
        logger.debug(() => `Entity ${entityId}: data source is empty, using empty object map`);
        return {};
    }
    const slice = source[entityId];
    if (!slice || typeof slice !== 'object' || Array.isArray(slice)) {
        logger.debug(() => `Entity ${entityId}: slice missing or invalid in source, using empty object map`);
        return {};
    }
    return slice;
}

export class SearchDataProvider {
    /**
     * @param {object} manifest
     * @param {(datasetId: string) => Promise<object>} loadDataset
     */
    constructor(manifest, loadDataset) {
        this.manifest = manifest;
        this.loadDataset = loadDataset;
        /** @type {Map<string, Record<string, object>>} */
        this.cache = new Map();
    }

    /**
     * @param {string} entityId
     * @returns {Promise<Record<string, object>>}
     */
    async getEntityData(entityId) {
        if (this.cache.has(entityId)) {
            return this.cache.get(entityId);
        }
        const config = getSearchEntityConfig(this.manifest, entityId);
        let data;
        if (config?.datasetId) {
            const loaded = await this.loadDataset(config.datasetId);
            data = extractEntityObjects(loaded ?? {}, entityId);
        } else {
            data = extractEntityObjects(this.manifest, entityId);
        }
        this.cache.set(entityId, data);
        return data;
    }

    /**
     * @param {string[]} entityIds
     * @returns {Promise<Record<string, Record<string, object>>>}
     */
    async getEntityDataMap(entityIds) {
        const uniqueIds = [...new Set(entityIds.filter(Boolean))];
        const entries = await Promise.all(
            uniqueIds.map(async(entityId) => [entityId, await this.getEntityData(entityId)])
        );
        return Object.fromEntries(entries);
    }
}
