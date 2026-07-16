/*
  Copyright (C) 2021 owner Roman Piontik R.Piontik@mail.ru

  Copyright (C) 2022 Sber

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

  In any derivative products, you must retain the information of
  owner of the original code and provide clear attribution to the project

  https://dochub.info

  The use of this product or its derivatives for any purpose cannot be a secret.


  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.

  Maintainers:
      R.Piontik <r.piontik@mail.ru>

  Contributors:
	  R.Piontik <r.piontik@mail.ru> - 2023
	  R.Piontik <r.piontik@mail.ru> - 2024
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2024
      Temnyakov Nikolay <temnjakovn@gmail.com>, Sber - 2024
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2025
*/

import request from './request.mjs';
import datasetDriver from '../../global/datasets/driver.mjs';
import jsonataDriver from '../helpers/jsonata.mjs';
import pathTool from '../../global/manifest/tools/path.mjs';
import entities from '../entities/entities.mjs';
import md5 from 'md5';
import source from '../../global/datasets/source.mjs';
import cache from '../storage/cache.mjs';
import { performanceLogger } from '../utils/logger/index.mjs';
import {isRolesMode} from '@back/utils/roles.mjs';
import {getCachePrefixWithDomain} from '@back/helpers/cachePrefixByDomain.mjs';

async function parseSource(context, data, subject, params, baseURI, datasetsWithError) {
	const sourceType = source.type(data);
	if (sourceType === 'id') {
		return await cache.pullFromDataCache(this.realCachePrefix, `{"path":"/datasets/${data}"}`, async() => {
			return await this.parentParseSource(context, data, subject, params, baseURI, undefined, datasetsWithError);
		})
		.catch((error) => {
			if(!datasetsWithError[data]) datasetsWithError[data] = {uri: baseURI, error};
			throw error;
		});
	} else {
		return await this.parentParseSource(context, data, subject, params, baseURI, undefined, datasetsWithError);
	}
}

/**
 * Возвращает драйвер датасетов
 *
 * @param {Object} storage - хранилище текущего манифеста
 * @param {string} roleId - идентификатор роли
 * @param {string} cachePrefix - используемый префикс кеша, по-умолчанию будет использоваться app.storage.hash
 * @returns {Object} - драйвер запросов к ресурсам
 */
export default function getDatasetDriver(storage, roleId, cachePrefix) {
	let realCachePrefix = cachePrefix;
	if (!realCachePrefix) {
		realCachePrefix = getCachePrefixWithDomain(storage);
	}
	let currentContext;

	if(roleId) {
		currentContext = storage.manifests[roleId];
		entities(currentContext);
	} else {
		currentContext = isRolesMode() ? storage.manifests.origin : storage.manifest;
	}
	
	const result = Object.assign({}, datasetDriver,
		{
			// Возвращаем метаданных об объекте
			pathResolver(path) {
				return {
					context: currentContext,
					subject: pathTool.get(currentContext, path),
					baseURI: storage.md5Map[md5(path)]
				};
			},
			realCachePrefix,
			parseSource,
			// Драйвер запросов к ресурсам
			request,
			// Драйвер запросов JSONata
			jsonataDriver: { ...jsonataDriver, getDatasetDriver: () => result },
			// Логгер расширенного логирования
			performanceLogger,
			// Включает/выключает трассировку запросов JSONata
			traceJsonata: process.env.VUE_APP_DOCHUB_JSONATA_ANALYZER?.toLowerCase() === 'y'
		});

	result.parentParseSource = datasetDriver.parseSource.bind(result);

	return result;
}
