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
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber

  Contributors:
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2026
      Marat Niyazmatov, Sber - 2026
*/

import helpers from '@back/controllers/helpers.mjs';
import datasets from '@back/helpers/datasets.mjs';
import { isRolesMode } from '@back/utils/roles.mjs';
import { getLoggerWithTag } from '@global/logger/v2/logger.mjs';
import { SEARCH_ALL_KEY } from '@global/search/constants.mjs';
import { SearchDataProvider } from '@global/search/search-data.mjs';
import { getFiltersForEntity, getFilterValueSuggestions, getSearchEntitiesList, performInEntitySearch, performSearchAll } from '@global/search/search-perform.mjs';
import { collectRelFields, parseRelTarget } from '@global/search/search-utils.mjs';

const LOG_TAG = 'controller-search';
const logger = getLoggerWithTag(LOG_TAG);

function getManifest(req) {
    let manifest = req.storage.manifest;
    if (isRolesMode()) {
        const roleId = req.userProfile.roleId;
        manifest = req.storage.manifests[roleId];
    }
    return manifest;
}

function createSearchDataProvider(req, manifest) {
    const roleId = isRolesMode() ? req.userProfile?.roleId : undefined;
    const datasetDriver = datasets(req.storage, roleId);
    return new SearchDataProvider(manifest, (datasetId) =>
        datasetDriver.releaseData(`/datasets/${datasetId}`)
    );
}

function collectRelEntityIds(fullSchema, choice, manifest) {
    return collectRelFields(fullSchema, choice, manifest)
        .map(rel => parseRelTarget(rel.relTarget)?.entityId)
        .filter(Boolean);
}

export default (app) => {
    // Endpoint for getting search categories list
    app.get('/seaf-core/api/core/storage/search/searchable-entities', async function(req, res) {
        if (!helpers.isServiceReady(app, res)) return;
        try {
            const manifest = getManifest(req);
            const result = getSearchEntitiesList(manifest);
            res.status(200).json(result);
        } catch (e) {
            logger.error(() => 'Error in searchable-entities: ' + e.message, e);
            res.status(500).json({ message: 'Unexpected error while composing searchable entities.' });
        }
    });

    // Endpoint for getting filters for a category
    app.get('/seaf-core/api/core/storage/search/entity-filters', async function(req, res) {
        if (!helpers.isServiceReady(app, res)) return;
        try {
            const choice = req.query.choice;
            if (!choice) {
                res.status(400)
                    .json({
                        error: 'query param "choice" required'
                    });
                return;
            }
            if (choice === SEARCH_ALL_KEY) {
                res.status(200).json([]);
                return;
            }
            const manifest = getManifest(req);
            const fullSchema = req.storage?.schema ?? manifest;
            const chosenEntitySchema = fullSchema?.properties?.[choice] ?? manifest.entities[choice]?.schema;
            if (!chosenEntitySchema) {
                res.status(400)
                    .json({
                        error: `Chosen entity ${choice} does not have schema.`
                    });
                return;
            }
            const responseBody = getFiltersForEntity(manifest, choice, fullSchema, chosenEntitySchema);
            res.status(200).json(responseBody);
        } catch (e) {
            logger.error(() => 'Error in entity-filters: ' + e.message, e);
            res.status(500).json({ message: 'Unexpected error while composing filters for entity.' });
        }
    });


    app.get('/seaf-core/api/core/storage/search/rel-suggestions', async function(req, res) {
        if (!helpers.isServiceReady(app, res)) return;
        try {
            const relTarget = req.query.relTarget;
            if (!relTarget || typeof relTarget !== 'string') {
                res.status(400).json({ error: 'query param "relTarget" required' });
                return;
            }
            const query = (req.query.query || '').trim().toLowerCase();
            if (query.length === 0) {
                res.status(200).json([]);
                return;
            }
            const manifest = getManifest(req);
            const parsed = parseRelTarget(relTarget);
            if (!parsed?.entityId) {
                res.status(200).json([]);
                return;
            }
            const provider = createSearchDataProvider(req, manifest);
            const entityData = await provider.getEntityData(parsed.entityId);
            const items = getFilterValueSuggestions(manifest, relTarget, query, entityData);
            res.status(200).json(items);
        } catch (e) {
            logger.error(() => 'Error in rel-suggestions: ' + e.message, e);
            res.status(500).json({ message: 'Unexpected error while composing suggestions for filter.' });
        }
    });

    app.post('/seaf-core/api/core/storage/search/search-run', async function(req, res) {
        if (!helpers.isServiceReady(app, res)) return;
        try {
            const reqBodyRaw = req.body;
            let error;
            if (!reqBodyRaw) {
                error = 'request must contains body';
            } else if (!reqBodyRaw.choice || typeof reqBodyRaw.choice !== 'string') {
                error = 'request body must contains string attr "choice"';
            } else if (!reqBodyRaw.filters || !Array.isArray(reqBodyRaw.filters)) {
                error = 'request body must contains array attr "filters"';
            }
            if (error) {
                res.status(400)
                    .json({
                        error: error
                    });
                return;
            }

            const manifest = getManifest(req);
            const choice = reqBodyRaw.choice;
            const queryWords = (reqBodyRaw.searchQuery || '')
                .trim()
                .split(/\s+/)
                .filter(Boolean)
                .map(w => w.trim());

            const provider = createSearchDataProvider(req, manifest);

            if (choice === SEARCH_ALL_KEY) {
                const searchableIds = getSearchEntitiesList(manifest).entities
                    .map(e => e.key)
                    .filter(k => k !== SEARCH_ALL_KEY);
                const entityDataMap = await provider.getEntityDataMap(searchableIds);
                const responseBody = performSearchAll(manifest, queryWords, entityDataMap);
                res.status(200).json(responseBody);
                return;
            }

            const entityDef = manifest.entities?.[choice];
            if (!entityDef) {
                res.status(400)
                    .json({
                        error: `Chosen entity ${choice} is not found.`
                    });
                return;
            }
            const fullSchema = req.storage?.schema ?? manifest;
            const chosenEntitySchema = fullSchema?.properties?.[choice] ?? entityDef?.schema;
            if (!chosenEntitySchema) {
                res.status(400)
                    .json({
                        error: `Chosen entity ${choice} does not have schema.`
                    });
                return;
            }

            const relEntityIds = collectRelEntityIds(fullSchema, choice, manifest);
            const entityDataMap = await provider.getEntityDataMap([choice, ...relEntityIds]);
            const filters = reqBodyRaw.filters;
            const responseBody = performInEntitySearch(
                manifest,
                fullSchema,
                chosenEntitySchema,
                choice,
                filters,
                queryWords,
                entityDataMap[choice],
                entityDataMap
            );
            res.status(200).json(responseBody);
        } catch (e) {
            logger.error(() => 'Error in search-run: ' + e.message, e);
            res.status(500).json({ message: 'Unexpected error while processing search request'});
        }
    });
};
