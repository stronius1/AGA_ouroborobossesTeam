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
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2023
      Vladislav Nefedov <clay.zenx@gmail.com>, Sber - 2023
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
*/

import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

const logger = getLoggerWithTag('BaseEntities');

// Обрабатывает кастомные сущности
export class BaseEntities {
	static appliedSchema = null;
	static lastKnownManifest = null;
	static entities = null;

	registerEntities(entities) {
		BaseEntities.entities = entities;
	}

	// Подключает мастер-схему для подсказок и валидации метамодели
	getMasterSchema() {
		throw new Error('Method getMasterSchema is not implemented');
	}


	// Устанавливает манифест, по которому будет сгенерирована схема при необходимости
	setManifest(manifest) {
		BaseEntities.lastKnownManifest = manifest;
	}

	// Генерирует список доступных типов документов
	// по-умолчанию, ограничением является просто строка
	makeDocTypesEnum() {
		return {
			'$doc-types': {
				type: 'string'
			}
		};
	}

	// Генерирует схему DataSet
	makeDataSetSchema(manifest) {
		return {
			$dataset: {
				type: 'string',
				enum: Object.keys(manifest.datasets || {})
			}
		};
	}


	// Генерируем схемы связей
	makeSubjectsRelationsSchema(manifest) {
		try {
			const rels = {};
			for (const entityId in manifest.entities || {}) {
				const objects = manifest.entities[entityId].objects;
				// Если сущность не публикует субъекты, то игнорируем ее
				if (!objects) continue;
				// Генерируем схемы связей с объектами
				for (const subjectId in objects) {
					const route = (objects[subjectId].route || '/').split('/');
					let location = manifest[entityId] || {};
					for (let i = 1; i < route.length; i++) {
						let pice = route[i];
						// если pice указывает на плейсхолдер inner и он не последний,
						// тогда ищем следующий за ним атрибут во всех сущностях, отобранных к этому шагу
						if (pice === '{inner}' && i < route.length - 1) {
							i++;
							pice = route[i];
							location = Object.assign({}, ...Object.values(location).map(el => el[pice]));
						} else { // иначе просто переходим вглубь объекта
							pice?.length && (location = location[route[i]] || {});
						}
					}
					const objId = `${entityId}.${subjectId}`;
					const locations = Object.keys(location);
					rels[objId] = {
						type: 'string',
						minLength: 1,
						enum: locations.length > 0 ? locations : undefined
					};
				}
			}
			return rels;
		} catch (e) {
			logger.error(() => `Error of building of relations enumeration! ${e.message}`, e);
			return {};
		}
	}

	// Генерирует перечисления для подсказок
	makeDefsEnum($defs, $rels) {
		let items = [];
		try {
			items = Object.keys($defs).map((item) => `"#/$defs/${item}"`);
			Object.keys($rels).map((item) => items.push(`"#/$rels/${item}"`));
		} catch (e) {
			logger.error(() => `Error of building of definitions enumeration! ${e.message}`, e);

		}
		return {
			'$defs': {
				type: 'string',
				enum: items
			}
		};
	}

	async queryEntitiesJSONSchema() {
		throw new Error('Method queryEntitiesJSONSchema is not implemented');
	}

	// загрузка схемы
	async loadSchema() {
		const queryResult = await this.queryEntitiesJSONSchema(BaseEntities.lastKnownManifest);

		const master = this.getMasterSchema();

		const $defs = {
			...master.$defs,
			...queryResult.$defs,
			...this.makeDataSetSchema(BaseEntities.lastKnownManifest)
		};

		const $rels = this.makeSubjectsRelationsSchema(BaseEntities.lastKnownManifest || {});

		// Превращаем схему в строку для передачи в плагин
		const schema = {
			...queryResult,
			properties: {
				...master.$entities,
				...queryResult.properties
			},
			$defs: {
				...$defs,
				...this.makeDefsEnum($defs, $rels),
				...this.makeDocTypesEnum()
			},
			// Добавляем схемы связей с субъектами сущностей
			$rels
		};

		logger.info(() => 'schema created');

		return schema;
	}

	// Пересоздаёт схему по установленному манифесту
	// Но только в случае, что схема уже создавалась (т.е. схемой уже хотя бы раз пользовались)
	async reloadSchema() {
		if (BaseEntities.appliedSchema !== null && BaseEntities.lastKnownManifest !== null) {
			BaseEntities.appliedSchema = await this.loadSchema();
		}
	}

	updateSchema(schema) {
		BaseEntities.appliedSchema = schema;
	}

	// Возвращает схему (создаёт, если ещё не создавалась и известен манифест, по которому создавать)
	static async getSchema() {
		if (BaseEntities.appliedSchema === null
			&& BaseEntities.lastKnownManifest !== null
			&& BaseEntities.entities !== null) {
				BaseEntities.appliedSchema = await BaseEntities.entities.loadSchema();
		}
		return BaseEntities.appliedSchema;
	}
}
