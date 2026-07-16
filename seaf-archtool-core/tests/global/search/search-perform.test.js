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
    getFilterValueSuggestions,
    getSearchEntitiesList,
    performInEntitySearch,
    performSearchAll
} from '@global/search/search-perform.mjs';

const manifest = {
    entities: {
        systems: {
            title: 'Systems',
            schema: {
                type: 'object',
                properties: {
                    title: { type: 'string' },
                    description: { type: 'string' }
                }
            }
        }
    },
    datasets: {
        ds_systems: {}
    },
    search: {
        entities: [
            { id: 'systems', dataset: 'ds_systems' }
        ]
    }
};

const entityData = {
    s1: { title: 'Alpha System', description: 'First' },
    s2: { title: 'Beta System', description: 'Second' }
};

const entitySchema = manifest.entities.systems.schema;

describe('search-perform', () => {
    it('getSearchEntitiesList includes dataset from config', () => {
        const result = getSearchEntitiesList(manifest);
        expect(result.entities).toEqual([
            { key: '__all__', title: 'Все' },
            { key: 'systems', title: 'Systems', dataset: 'ds_systems' }
        ]);
    });

    it('getFilterValueSuggestions uses preloaded entityData', () => {
        const items = getFilterValueSuggestions(manifest, 'systems.systems', 'alpha', entityData);
        expect(items).toEqual([{ text: 'Alpha System', value: 'Alpha System' }]);
    });

    it('performInEntitySearch uses preloaded entityData', () => {
        const results = performInEntitySearch(
            manifest,
            manifest,
            entitySchema,
            'systems',
            [],
            ['alpha'],
            entityData
        );
        expect(results).toHaveLength(1);
        expect(results[0].title).toBe('Alpha System');
        expect(results[0]._sfa_key).toBe('s1');
    });

    it('performSearchAll uses entityDataMap', () => {
        const results = performSearchAll(manifest, ['beta'], { systems: entityData });
        expect(results).toHaveLength(1);
        expect(results[0].title).toBe('Beta System');
    });
});
