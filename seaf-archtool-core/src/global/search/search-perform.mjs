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
  restrictions under the License.

  Maintainers:
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber

  Contributors:
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2026
      Marat Niyazmatov, Sber - 2026
*/

import { REL_SUGGESTIONS_LIMIT, SEARCH_ALL_KEY, SEARCH_RESULT_LIMIT } from './constants.mjs';
import { filterValue } from './filter-utils.mjs';
import { getSearchEntityConfig } from './search-config.mjs';
import { buildSearchResultItem, checkSearchQueryMatch, collectRelFields, collectTopLevelProperties, getObjectTitle, getSearchableEntities, getTitleDescriptionFields, parseRelTarget } from './search-utils.mjs';

/**
 * Gets suggestions for filter values based on a relationship target and search query.
 * 
 * @param {Object} manifest - The manifest object containing entity data and definitions
 * @param {string} relTarget - The relationship target string to parse and search
 * @param {string} query - The search query to match against titles and aliases (case-insensitive)
 * @param {Record<string, object>} [entityData] - Preloaded entity objects map
 * @returns {Array<{text: string, value: string}>} An array of suggestion objects with text and value properties,
 *          limited by REL_SUGGESTIONS_LIMIT. Returns empty array if target is invalid or no matches found.
 */
export function getFilterValueSuggestions(manifest, relTarget, query, entityData) {
    const parsedTarget = parseRelTarget(relTarget);
    if (!parsedTarget) {
        return [];
    }
    const { entityId } = parsedTarget;
    const objects = entityData ?? manifest?.[entityId];
    if (!objects || typeof objects !== 'object') {
        return [];
    }
    const entityDef = manifest?.entities?.[entityId];
    const allProperties = entityDef?.schema ? collectTopLevelProperties(entityDef.schema) : null;
    const { titleKey } = getTitleDescriptionFields(allProperties || {});

    const items = [];
    for (const [id, obj] of Object.entries(objects)) {
        const objWithKey = { ...obj, _sfa_key: id };
        const title = getObjectTitle(objWithKey, { titleKey });
        const aliases = Array.isArray(obj.aliases) ? obj.aliases.map(a => String(a)) : [];
        const searchText = [title, ...aliases].filter(Boolean).join(' ').toLowerCase();
        if (!searchText.includes(query)) continue;
        items.push({ text: title, value: title });
        if (items.length >= REL_SUGGESTIONS_LIMIT) break;
    }
    return items;
}

/**
 * Gets filter configuration for a specific entity based on its schema.
 * 
 * @param {Object} manifest - The manifest object containing entity definitions
 * @param {string} category - The entity category to search for relationship fields
 * @param {Object} fullSchema - The full schema to extract relationship fields from
 * @param {Object} chosenEntitySchema - The schema of the entity to get filters for
 * @returns {Array<Object>} An array of filter objects with properties:
 *   - key: string - The property key
 *   - title: string - The display title
 *   - type: string - The filter type ('string', 'number', 'integer', 'enum', or 'rel')
 *   - enumValues: Array - For enum types, the possible values
 *   - relTarget: string - For relationship types, the target entity
 *   - isArray: boolean - For relationship types, whether it's an array
 */
export function getFiltersForEntity(manifest, category, fullSchema, chosenEntitySchema) {
    const allProperties = collectTopLevelProperties(chosenEntitySchema);
    let output = [];
    for (const [key, value] of Object.entries(allProperties)) {
        // If there is a relationship field, skip it here, it will be added below with collectRelFields
        if (!value.$ref && (value.type === 'string' || value.type === 'number' || value.type === 'integer' || value.enum)) {
            output.push({
                key: key,
                title: value.title,
                type: value.type || 'enum',
                enumValues: value.enum
            });
        }
    }
    // Add relationship fields that we skipped above
    const relFields = collectRelFields(fullSchema, category, manifest);
    for (const rel of relFields) {
        output.push({
            key: rel.key,
            title: rel.title ?? rel.key,
            type: 'rel',
            relTarget: rel.relTarget,
            isArray: rel.isArray
        });
    }
    return output;
}

/**
 * Gets the list of searchable entities from the manifest.
 * 
 * @param {Object} manifest - The manifest object containing entity definitions and data
 * @returns {Object} An object with two properties:
 *   - entities: Array<{key: string, title: string, dataset?: string}> - List of searchable entities including 'All' option
 *   - hasCompanies: boolean - Whether the manifest contains company data
 */
export function getSearchEntitiesList(manifest) {
    const searchableKeys = getSearchableEntities(manifest);
    const entitiesList = [{ key: SEARCH_ALL_KEY, title: 'Все' }];
    for (const key of searchableKeys) {
        const ent = manifest.entities[key];
        const config = getSearchEntityConfig(manifest, key);
        const item = { key, title: ent.title };
        if (config?.datasetId) {
            item.dataset = config.datasetId;
        }
        entitiesList.push(item);
    }
    const companies = manifest.companies || {};
    const hasCompanies = typeof companies === 'object' && Object.keys(companies).length > 0;
    return {
        entities: entitiesList,
        hasCompanies
    };
}

/**
 * Performs a search across all searchable entities in the manifest.
 * 
 * @param {Object} manifest - The manifest object containing entity data and definitions
 * @param {Array<string>} queryWords - Array of words from the search query to match against
 * @param {Record<string, Record<string, object>>} [entityDataMap] - Preloaded entity data per entityId
 * @returns {Array<Object>} Array of search result items, limited by SEARCH_RESULT_LIMIT.
 *   Each item is built by buildSearchResultItem with entity data, title, and metadata.
 */
export function performSearchAll(manifest, queryWords, entityDataMap = {}) {
  const companies = manifest.companies || {};
  const searchableKeys = getSearchableEntities(manifest);
  const responseBody = [];

  for (const entityId of searchableKeys) {
    if (responseBody.length >= SEARCH_RESULT_LIMIT) break;
    const entityData = entityDataMap[entityId] ?? manifest[entityId];
    const entityDef = manifest.entities[entityId];
    if (!entityData || typeof entityData !== 'object' || !entityDef?.schema)
      continue;
    const allProperties = collectTopLevelProperties(entityDef.schema);
    const { titleKey, descKey } = getTitleDescriptionFields(allProperties);

    for (const [key, value] of Object.entries(entityData)) {
      if (responseBody.length >= SEARCH_RESULT_LIMIT) break;
      const match = checkSearchQueryMatch(
        queryWords,
        key,
        value,
        titleKey,
        descKey
      );
      if (match) {
        responseBody.push(
          buildSearchResultItem(
            key,
            value,
            entityId,
            entityDef.title || entityId,
            companies,
            allProperties,
            entityDef
          )
        );
      }
    }
  }
  return responseBody;
}

/**
 * Performs a search within a specific entity with optional filters.
 * 
 * @param {Object} manifest - The manifest object containing entity data
 * @param {Object} fullSchema - The full schema to extract relationship fields from
 * @param {Object} chosenEntitySchema - The schema of the entity to search within
 * @param {string} choice - The entity key to search within
 * @param {Array<Object>} filters - Array of filter objects to apply to results
 * @param {Array<string>} queryWords - Array of words from the search query to match against
 * @param {Record<string, object>} [entityData] - Preloaded objects for the searched entity
 * @param {Record<string, Record<string, object>>} [entityDataMap] - Preloaded data for rel filter resolution
 * @returns {Array<Object>} Array of search result items that match the query and filters.
 *   Each item is built by buildSearchResultItem with entity data, title, and metadata.
 */
export function performInEntitySearch(manifest, fullSchema, chosenEntitySchema, choice, filters, queryWords, entityData, entityDataMap = {}) {
  const companies = manifest.companies || {};
  const allProperties = collectTopLevelProperties(chosenEntitySchema);
  const entityDef = manifest.entities[choice];
  const relFields = collectRelFields(fullSchema, choice, manifest);
  const relFieldsMap = Object.fromEntries(
    relFields.map((r) => [
      r.key,
      { relTarget: r.relTarget, isArray: r.isArray }
    ])
  );
  const { titleKey, descKey } = getTitleDescriptionFields(allProperties);

  const objects = entityData ?? manifest[choice];
  if (!objects || typeof objects !== 'object') {
    return [];
  }

  let responseBody = [];
  for (const [key, value] of Object.entries(objects)) {
    const match = checkSearchQueryMatch(
      queryWords,
      key,
      value,
      titleKey,
      descKey
    );
    const isValidByFilter =
      match &&
      filterValue({
        filters,
        entity: value,
        entitySchema: allProperties,
        manifest,
        relFieldsMap,
        entityDataMap
      });
    if (isValidByFilter) {
      responseBody.push(
        buildSearchResultItem(
          key,
          value,
          choice,
          entityDef.title || choice,
          companies,
          allProperties,
          entityDef
        )
      );
    }
  }
  return responseBody;
}
