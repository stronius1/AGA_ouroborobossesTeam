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

import { describe, expect, it, jest } from '@jest/globals';
import { SearchDataProvider, extractEntityObjects } from '@global/search/search-data.mjs';

const manifest = {
    entities: {
        'kadzo.systems': {
            title: 'Systems',
            schema: { type: 'object' }
        }
    },
    datasets: {
        ds_systems: { source: '($)' }
    },
    'kadzo.systems': {
        lake1: { title: 'Lake System' }
    },
    search: {
        entities: [
            { id: 'kadzo.systems' },
            { id: 'kadzo.integrations', dataset: 'ds_integrations' }
        ]
    }
};

describe('search-data', () => {
    it('extractEntityObjects reads slice by entityId from lake-like structure', () => {
        const source = {
            'kadzo.systems': {
                s1: { title: 'System 1' },
                s2: { title: 'System 2' }
            }
        };
        expect(extractEntityObjects(source, 'kadzo.systems')).toEqual({
            s1: { title: 'System 1' },
            s2: { title: 'System 2' }
        });
    });

    it('extractEntityObjects returns empty map when slice missing', () => {
        expect(extractEntityObjects({}, 'kadzo.systems')).toEqual({});
        expect(extractEntityObjects(null, 'kadzo.systems')).toEqual({});
    });

    it('extractEntityObjects returns empty map for empty dataset slice', () => {
        expect(extractEntityObjects({ 'kadzo.softwares': {} }, 'kadzo.softwares')).toEqual({});
        expect(extractEntityObjects({}, 'kadzo.softwares')).toEqual({});
    });

    it('SearchDataProvider loads from lake without dataset', async() => {
        const provider = new SearchDataProvider(manifest, jest.fn());
        const data = await provider.getEntityData('kadzo.systems');
        expect(data).toEqual({ lake1: { title: 'Lake System' } });
    });

    it('SearchDataProvider loads from dataset and extracts entity slice', async() => {
        const loadDataset = jest.fn().mockResolvedValue({
            'kadzo.integrations': {
                i1: { title: 'Integration 1' }
            }
        });
        const provider = new SearchDataProvider(manifest, loadDataset);
        const data = await provider.getEntityData('kadzo.integrations');
        expect(loadDataset).toHaveBeenCalledWith('ds_integrations');
        expect(data).toEqual({ i1: { title: 'Integration 1' } });
    });

    it('SearchDataProvider returns empty map when dataset has no entity slice', async() => {
        const loadDataset = jest.fn().mockResolvedValue({});
        const provider = new SearchDataProvider(manifest, loadDataset);
        const data = await provider.getEntityData('kadzo.integrations');
        expect(data).toEqual({});
    });

    it('SearchDataProvider caches extracted entity data', async() => {
        const loadDataset = jest.fn().mockResolvedValue({
            'kadzo.integrations': { i1: { title: 'Integration 1' } }
        });
        const provider = new SearchDataProvider(manifest, loadDataset);
        await provider.getEntityData('kadzo.integrations');
        await provider.getEntityData('kadzo.integrations');
        expect(loadDataset).toHaveBeenCalledTimes(1);
    });

    it('getEntityDataMap loads multiple entities in parallel', async() => {
        const loadDataset = jest.fn().mockResolvedValue({
            'kadzo.integrations': { i1: { title: 'Integration 1' } }
        });
        const provider = new SearchDataProvider(manifest, loadDataset);
        const map = await provider.getEntityDataMap(['kadzo.systems', 'kadzo.integrations', 'kadzo.systems']);
        expect(map['kadzo.systems']).toEqual({ lake1: { title: 'Lake System' } });
        expect(map['kadzo.integrations']).toEqual({ i1: { title: 'Integration 1' } });
        expect(loadDataset).toHaveBeenCalledTimes(1);
    });
});
