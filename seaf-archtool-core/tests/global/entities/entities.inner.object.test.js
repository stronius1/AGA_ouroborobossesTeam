/*
  Copyright (C) 2025 Sber

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
    Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025

  Contributors:
    Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
*/

import {describe, expect} from '@jest/globals';
import manifest from '../__mocks__/entities/inner-object/manifest.json';
import {BaseEntities} from '../../../src/global/entities/entities.mjs';


describe.skip('entities.inner', () => {
  test('[makeSubjectsRelationsSchema]: Парсинг вложенных объектов', () => {
    // Проверяем на заготовленном манифесте, из которого удалено все лишнее, лежит в моках
    let rels = new BaseEntities().makeSubjectsRelationsSchema(manifest);

    // Количество создаваемых rels, должны включать 3 штуки, включая вложенные
    let relsKeys = Object.keys(rels);
    expect(relsKeys).toHaveLength(3);
    expect(relsKeys).toEqual(expect.arrayContaining([
      'kadzo.v2023.systems.systems',
      'kadzo.v2023.systems.systems.integrations',
      'kadzo.v2023.systems.systems.integrations.path'
    ]));

    // Проверяем список проиндексированных систем (базовая сущность)
    let systemObjects = rels['kadzo.v2023.systems.systems'].enum;
    expect(systemObjects).toHaveLength(3);
    expect(systemObjects).toEqual(expect.arrayContaining([
      'ecogroup.berezka.systems.berezka.test',
      'ecogroup.berezka.systems.berezka.catalog.test',
      'ecogroup.berezka.systems.crm.test'
    ]));

    // Проверяем список проиндексированных интеграционных объектов в системах (1 уровень вложенности)
    let integrationObjects = rels['kadzo.v2023.systems.systems.integrations'].enum;
    expect(integrationObjects).toHaveLength(3);
    expect(integrationObjects).toEqual(expect.arrayContaining([
      'ecogroup.berezka.systems.berezka.test.integration.outside',
      'ecogroup.berezka.systems.berezka.catalog.test.integration.outside',
      'ecogroup.berezka.systems.crm.test.integration.outside'
    ]));


    // Проверяем список проиндексированных путей интеграционных объектов в системах (2 уровень вложенности)
    let integrationPathObjects = rels['kadzo.v2023.systems.systems.integrations.path'].enum;
    expect(integrationPathObjects).toHaveLength(2);
    expect(integrationPathObjects).toEqual(expect.arrayContaining([
      'ecogroup.berezka.systems.berezka.test.integration.outside.path',
      'ecogroup.berezka.systems.berezka.catalog.test.integration.outside.path'
    ]));
  });
});
