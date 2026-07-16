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

import { getLoggerWithTag } from '@global/logger/v2/logger.mjs';

const LOG_TAG = 'search-config';
const logger = getLoggerWithTag(LOG_TAG);

/**
 * @typedef {Object} SearchEntityConfig
 * @property {string} entityId
 * @property {string} [datasetId]
 */

/**
 * @param {unknown} entry
 * @returns {SearchEntityConfig|null}
 */
export function parseSearchEntityEntry(entry) {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
        return null;
    }
    const entityId = entry.id;
    if (!entityId || typeof entityId !== 'string') {
        return null;
    }
    const datasetId = entry.dataset;
    if (datasetId != null && typeof datasetId !== 'string') {
        return null;
    }
    return {
        entityId,
        datasetId: datasetId || undefined
    };
}

/**
 * @param {object} manifest
 * @returns {Map<string, SearchEntityConfig>}
 */
export function parseSearchEntitiesConfig(manifest) {
    const result = new Map();
    const entries = manifest?.search?.entities;
    if (!Array.isArray(entries)) {
        return result;
    }
    for (const entry of entries) {
        const parsed = parseSearchEntityEntry(entry);
        if (!parsed) {
            logger.warn(() => `Invalid search.entities entry: ${JSON.stringify(entry)}`);
            continue;
        }
        result.set(parsed.entityId, parsed);
    }
    return result;
}

/**
 * @param {object} manifest
 * @param {string} entityId
 * @returns {SearchEntityConfig|null}
 */
// TODO: ERA-2782 - some functions in this file run very often, their output could be calculated once during manifest creation.
export function getSearchEntityConfig(manifest, entityId) {
    return parseSearchEntitiesConfig(manifest).get(entityId) ?? null;
}

/**
 * @param {object} manifest
 * @param {SearchEntityConfig} config
 * @returns {boolean}
 */
function isSearchEntityAvailable(manifest, config) {
    const ent = manifest?.entities?.[config.entityId];
    if (!ent?.schema || !ent?.title) {
        return false;
    }
    if (config.datasetId) {
        if (!manifest?.datasets?.[config.datasetId]) {
            logger.warn(() => `Search entity ${config.entityId}: dataset ${config.datasetId} not found in manifest`);
            return false;
        }
        return true;
    }
    const lakeData = manifest?.[config.entityId];
    return lakeData && typeof lakeData === 'object';
}

/**
 * @param {object} manifest
 * @returns {string[]}
 */
export function getSearchableEntityIds(manifest) {
    const configMap = parseSearchEntitiesConfig(manifest);
    if (configMap.size > 0) {
        return [...configMap.values()]
            .filter(config => isSearchEntityAvailable(manifest, config))
            .map(config => config.entityId);
    }
    const entities = manifest?.entities || {};
    return Object.keys(entities).filter(key => {
        const ent = entities[key];
        return ent?.schema && ent?.title && manifest[key] && typeof manifest[key] === 'object';
    });
}
