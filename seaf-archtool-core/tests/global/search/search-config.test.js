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

import { describe, expect, it } from '@jest/globals';
import {
    getSearchEntityConfig,
    getSearchableEntityIds,
    parseSearchEntitiesConfig,
    parseSearchEntityEntry
} from '@global/search/search-config.mjs';

const baseManifest = {
    entities: {
        'lake.entity': {
            title: 'Lake Entity',
            schema: { type: 'object', properties: { title: { type: 'string' } } }
        },
        'dataset.entity': {
            title: 'Dataset Entity',
            schema: { type: 'object', properties: { title: { type: 'string' } } }
        },
        'missing.data': {
            title: 'Missing Data',
            schema: { type: 'object' }
        }
    },
    datasets: {
        ds_systems: { source: '($)' }
    },
    'lake.entity': {
        obj1: { title: 'One' }
    },
    search: {
        entities: [
            { id: 'lake.entity' },
            { id: 'dataset.entity', dataset: 'ds_systems' },
            { id: 'missing.data' },
            { id: 'unknown.entity', dataset: 'missing_ds' }
        ]
    }
};

describe('search-config', () => {
    it('parseSearchEntityEntry parses id and optional dataset', () => {
        expect(parseSearchEntityEntry({ id: 'a' })).toEqual({ entityId: 'a', datasetId: undefined });
        expect(parseSearchEntityEntry({ id: 'a', dataset: 'ds' })).toEqual({ entityId: 'a', datasetId: 'ds' });
        expect(parseSearchEntityEntry('a')).toBeNull();
        expect(parseSearchEntityEntry({ dataset: 'ds' })).toBeNull();
    });

    it('parseSearchEntitiesConfig builds map from manifest', () => {
        const map = parseSearchEntitiesConfig(baseManifest);
        expect(map.size).toBe(4);
        expect(map.get('dataset.entity')).toEqual({ entityId: 'dataset.entity', datasetId: 'ds_systems' });
    });

    it('getSearchEntityConfig returns config for entity', () => {
        expect(getSearchEntityConfig(baseManifest, 'dataset.entity')).toEqual({
            entityId: 'dataset.entity',
            datasetId: 'ds_systems'
        });
        expect(getSearchEntityConfig(baseManifest, 'nope')).toBeNull();
    });

    it('getSearchableEntityIds filters by schema, lake data or dataset', () => {
        const ids = getSearchableEntityIds(baseManifest);
        expect(ids).toEqual(['lake.entity', 'dataset.entity']);
    });

    it('getSearchableEntityIds falls back to all lake entities when search.entities absent', () => {
        const manifest = {
            entities: baseManifest.entities,
            'lake.entity': baseManifest['lake.entity']
        };
        expect(getSearchableEntityIds(manifest)).toEqual(['lake.entity']);
    });
});
