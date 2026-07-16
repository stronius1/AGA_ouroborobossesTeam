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
      Vladislav Nefedov <clay.zenx@gmail.com>, Sber - 2023
	  R.Piontik <r.piontik@mail.ru> - 2024
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2024
      Temnyakov Nikolay <temnjakovn@gmail.com>, Sber - 2024
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2025
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
*/

import manifestParser from '@global/manifest/parser3/index.mjs';
import cache from './cache.mjs';
import md5 from 'md5';
import events from '../helpers/events.mjs';
import validators from '../helpers/validators.mjs';
import entities from '../entities/entities.mjs';
import objectHash from 'object-hash';
import '../helpers/env.mjs';
import jsonataDriver from '../helpers/jsonata.mjs';
import jsonataFunctions from '@global/jsonata/functions.mjs';
import {newManifest, loader, isRolesMode, DEFAULT_ROLE} from '../utils/roles.mjs';
import uriTool, {addFileProtocolIfNoProtocol} from '../helpers/uri.mjs';
import datasetsWarmup from '../cluster/datasets-warmup.mjs';
import {BaseEntities} from '@global/entities/entities.mjs';
import { jsonataPerformanceLogger } from '../utils/logger/index.mjs';
import userMenuWarmup from '../cluster/user-menu-warmup.mjs';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import {calcNewDatasetsChecksum} from '@back/helpers/recalculate-datasets.mjs';
import {getDsChecksumPrefixWithDomain} from '@back/helpers/cachePrefixByDomain.mjs';

const LOG_TAG = 'storage-manager';
const logger = getLoggerWithTag(LOG_TAG);
logger.info(() => `Storage manager uses manifest parser ${manifestParser.parserVersion}`);

manifestParser.logger = logger;
manifestParser.cache = cache;
manifestParser.onError = (errorType, errorData) => {
	logger.error(() => `Error of loading manifest (${errorType}) by url ${errorData.uri} -- ${errorData.error}`);
};

// eslint-disable-next-line no-unused-vars
manifestParser.onStartReload = (parser) => {
	logger.info(() => 'Manifest start reloading');
};

// eslint-disable-next-line no-unused-vars
manifestParser.onReloaded = (parser) => {
	logger.info(() => 'Manifest is reloaded');
};

export default {
	// Регистрация пользовательских функций
	pushRequest: manifestParser.pushRequest,
	resetCustomFunctions(storage) {
		jsonataDriver.customFunctions = () => {
			return jsonataFunctions(jsonataDriver, storage.functions || {}, jsonataPerformanceLogger);
		};

	},
	reloadManifest: async function(uri) {

		logger.info(() => 'Run full reload manifest');
		// Загрузку начинаем с виртуального манифеста
		cache.errorClear();
		let storageManifest = {};
		let createManifest = async function() {
			await manifestParser.clean();
			await manifestParser.startLoad();

			let metamodel = (process.env.VUE_APP_DOCHUB_METAMODEL || '/metamodel/root.yaml');
			metamodel = addFileProtocolIfNoProtocol(metamodel);
			logger.info(() => `start import metamodel by url ${metamodel}`);
			await manifestParser.import(metamodel);
			// Подключаем документацию, если нужно
			if ((process.env.VUE_APP_DOCHUB_APPEND_DOCHUB_DOCS || 'y').toLowerCase() === 'y') {
				let documentationUrl = 'file:///documentation/dochub.yaml';
				logger.info(() => `start import docs by default url ${documentationUrl}`);
				await manifestParser.import(documentationUrl);
			} else {
				logger.info(() => `import docs disabled by VUE_APP_DOCHUB_APPEND_DOCHUB_DOCS = ${process.env.VUE_APP_DOCHUB_APPEND_DOCHUB_DOCS}`);
			}
			if (uri) {
				uri = addFileProtocolIfNoProtocol(uri);
				logger.info(() => `start import manifest by url ${uri}`);
				await manifestParser.import(uri);
			} else if (process.env.VUE_APP_DOCHUB_ROOT_MANIFEST) {
				let envParamManifest = process.env.VUE_APP_DOCHUB_ROOT_MANIFEST;
				envParamManifest = addFileProtocolIfNoProtocol(envParamManifest);
				logger.info(() => `start import manifest by env param ${envParamManifest}`);
				await manifestParser.import(envParamManifest);
			} else {
				logger.info(() => 'no manifest to import, params uri and env (process.env.VUE_APP_DOCHUB_ROOT_MANIFEST) not exist value');
			}
			manifestParser.checkAwaitedPackages();
			manifestParser.checkLoaded();
			await manifestParser.stopLoad();
		};

		let createRoleManifest = async function() {
			// загружаю основной файл с ролями
			const {URI} =  global.$roles;
			try {
				const url = uriTool.makeURL(URI).url;
				const manifest = await loader(url);
				// загружаю правила по умолчанию
				const defaultUrl = uriTool.makeURL('default.yaml', URI).url;
				const defaultRoles = await loader(defaultUrl);
				const systemRoles = defaultRoles?.roles || [];
				const exclude = defaultRoles?.exclude || [];

				for (const role in manifest?.roles) {
					const filters = systemRoles.concat(manifest?.roles[role]);
					logger.debug(() => `start build manifest for role [${role}]`);
					storageManifest.manifests[role] = newManifest(storageManifest.manifests.origin, exclude, filters);
					logger.debug(() => `finish build manifest for role [${role}]`);
				}
			} catch (e) {
				logger.error(() => `Ошибка при загрузке манифеста с ролями ${e.uri || URI}: ${e.message}`);
			}
		};

		await createManifest();

		let baseManifest = manifestParser.manifest;
		if (!baseManifest.datasets) {
			baseManifest.datasets = {};
		}

		if(isRolesMode()) {
			storageManifest.manifests = {origin: baseManifest};
			Object.freeze(storageManifest.manifests.origin);
			await createRoleManifest();
			baseManifest = storageManifest.manifests[DEFAULT_ROLE];
		}

		// Полный манифест. Если включена ролевая модель, то берем манифест origin (в котором есть все элементы), без ролевой просто манифест
		const fullManifest = isRolesMode() ? storageManifest.manifests : manifestParser.manifest;
		const hash = objectHash(fullManifest);
		entities(isRolesMode() ? storageManifest.manifests.origin : manifestParser.manifest);

		logger.info(() => 'Full reload is done');
		const result = {
			manifest: baseManifest,
			parser: manifestParser,
			manifestHash: hash, // HASH состояния для контроля в кластере
			mergeMap: {},								// Карта склейки объектов
			md5Map: {}, 								// Карта путей к ресурсам по md5 пути
			manifests: {...storageManifest.manifests},
			roleId: DEFAULT_ROLE,
			// Ошибки, которые возникли при загрузке манифестов
			// по умолчанию заполняем ошибками, которые возникли при загрузке
			problems: Object.keys(cache.errors || {}).map((key) => cache.errors[key]) || [],
			repositorySources: [...manifestParser.repositorySources]
		};

		// Выводим информацию о текущем hash состояния
		logger.info(() => `Hash of manifest is ${result.manifestHash}`);

		// Если есть ошибки загрузки, то дергаем callback 
		result.problems.length && events.onFoundLoadingError();

		for (const path in manifestParser.mergeMap) {
			result.mergeMap[path] = manifestParser.mergeMap[path].map((url) => {
				const hash = md5(path);
				result.md5Map[hash] = url;
				return `backend://${hash}/`;
			});
		}
		return result;
	},
	applyManifest: async function(storage, isCluster = false, isPrimary = false, oldManifestMeta) {
		// При включенной ролевой модели берем функции из полного манифеста (origin)
		this.resetCustomFunctions(isRolesMode() ? storage.manifests.origin : storage.manifest);
		if (isCluster && !isPrimary) {
			manifestParser.isManifestBuilded = true;
			storage.parser = {
				...storage.parser,
				mergeMap: storage.mergeMap,
				manifest: storage.manifest
			};
			entities(storage.manifest, storage.schema);
		} else {
			storage.schema = await BaseEntities.getSchema();
			const newChecksums = await calcNewDatasetsChecksum(storage);
			const datasetHash = md5(JSON.stringify(newChecksums));
			storage.datasetHash = datasetHash;
			storage.hash = md5(storage.manifestHash + datasetHash);
			const cachePrefix = getDsChecksumPrefixWithDomain(storage);
			await cache.updateInDataCache(cachePrefix, storage.datasetHash, () => newChecksums);
            if (storage.warmupNeeded) {
                await datasetsWarmup(storage, cache, isCluster, oldManifestMeta, newChecksums);
				await cache.updateInDataCache(cachePrefix, storage.datasetHash, () => newChecksums);
                await userMenuWarmup(storage, cache);
            }
			await validators(storage);        // Выполняет валидаторы
		}
		return storage;
	}
};

