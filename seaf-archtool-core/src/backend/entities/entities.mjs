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
*/

import {BaseEntities} from '../../global/entities/entities.mjs';
import queries from '../../global/jsonata/queries.mjs';
import driver from '../helpers/jsonata.mjs';
import yaml from 'yaml';
import {loadFromAssets} from '../storage/cache.mjs';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

const logger = getLoggerWithTag('b/e/entities');

class BackendEntities extends BaseEntities {

  // Подключает мастер-схему для подсказок и валидации метамодели
  getMasterSchema() {
    return yaml.parse(loadFromAssets('master-schema.yaml'));
  }
  async queryEntitiesJSONSchema(manifest) {
    const query = queries.makeQuery(queries.QUERIES[queries.IDS.JSONSCEMA_ENTITIES]);
    let result = null;
    try {
      result = await driver
        .expression(query)
        .evaluate(manifest);
    } catch (e) {
        logger.error(() => 'Ошибка выполнения JSONata выражения', e);
        throw e;
      }
      return result;
  }
}


// Регистрирует кастомные сущности
export default function(manifest, schema) {
  const entities = new BackendEntities();
  entities.registerEntities(entities);
  entities.setManifest(manifest);
  if (schema) {
    entities.updateSchema(schema);
  } else {
    void entities.reloadSchema();
  }
}
