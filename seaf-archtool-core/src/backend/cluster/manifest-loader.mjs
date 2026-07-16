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
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2024, 2025
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2025
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
*/

import { ClusterCache } from './cache.mjs';
import {v4 as uuidv4} from 'uuid';
import storeManager from '../storage/manager.mjs';
import { parentPort } from 'node:worker_threads';
import {
    CLUSTER_MANIFEST, CLUSTER_MANIFEST_META,
    CLUSTER_MANIFEST_PARSER, CLUSTER_MANIFEST_UPDATE_TIME_KEY,
    DEFAULT_PERMISSION_WITHOUT_ROLE_MODEL_V2
} from './constants.mjs';
import {changeLoggerImpl, getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import {mainLogger} from '@back/utils/logger/constLoggers.mjs';
import {makeURIByBaseURI} from '@global/manifest/tools/uri.mjs';
import storageCache from '@back/storage/cache.mjs';
import {addFileProtocolIfNoProtocol} from '@back/helpers/uri.mjs';
import {validateRootManifest} from '@back/helpers/rootManifestVersionCheck.mjs';
import {ROLES_MODE_V2_ENABLED, ROLES_MODE_V2_VALUE} from '@back/helpers/env.mjs';

changeLoggerImpl(mainLogger);

const LOG_TAG = 'manifest_loader';
const logger = getLoggerWithTag(LOG_TAG);

logger.info(() => `Manifest loader process node params: ${process.execArgv}; and options: ${process.env.NODE_OPTIONS}`);

const clusterCache = new ClusterCache();

let parentFile = process.env.VUE_APP_DOCHUB_ROOT_MANIFEST;
parentFile = addFileProtocolIfNoProtocol(parentFile);
const rootDataRaw = await storageCache.request(parentFile);
let rootData = rootDataRaw.data;
validateRootManifest(rootData);
rootData.imports = convertPermissionToLowerCase(rootData.imports);
throwIfPermissionDuplicates(rootData);
const reloadStart = Date.now();

const cacheDriver = await clusterCache.getClusterCache();
await clusterCache.setRootManifestData(rootData); // сохраняем root манифест, чтобы при запросах перезагрузки его учитывать

const countImportsInRoot = rootData.imports.length;
const isV2RolesEnabled = ROLES_MODE_V2_ENABLED;
logger.info(() => `in root manifest found ${countImportsInRoot} imports and isV2RolesEnabled ${isV2RolesEnabled}`);

if (!isV2RolesEnabled && countImportsInRoot > 1) {
    // Если ролевая модель v2 выключена, то мы можем работать только с 1 доменом доступным всем
    throw new Error('If the role model is disabled, the root manifest cannot contain more than 1 imports. ' +
        `Value of VUE_APP_DOCHUB_ROLES_MODEL_V2=${ROLES_MODE_V2_VALUE}, count imports = ${countImportsInRoot}`);
}

let actualManifestState = await clusterCache.getActualManifestTimes();
if (!actualManifestState || typeof actualManifestState !== 'object') { // если данных об актуальных версиях манифестов совсем нет, то заполняем полностью
    actualManifestState = {};
    for (let el of rootData.imports) {
        actualManifestState[el.alias] = -1;
    }
    await clusterCache.saveActualManifestTimes(actualManifestState);
} else { // иначе если текущее есть, то добавляем только новые манифесты в список
    let hasNewImport = false;
    for (let el of rootData.imports) {
        if (!actualManifestState[el.alias]) {
            hasNewImport = true; // если новый манифест добавили, то меняем флаг, чтобы потом сохранить
            actualManifestState[el.alias] = -1;
        }
    }
    if (hasNewImport) {
        await clusterCache.saveActualManifestTimes(actualManifestState);
    }
}

if (!isV2RolesEnabled && countImportsInRoot === 1) {
    // Если ролевая модель выключена и домен указан один, то грузим его с заглушкой домена, чтобы дать доступ всем
    // (обратная совместимость) с режимом без ролевой модели
    const _import = rootData.imports[0];
    const expectTimeManifest = await clusterCache.getExpectTimeManifest(_import.alias);
    const actualTimeManifest = actualManifestState[_import.alias];
    if (expectTimeManifest > actualTimeManifest) {
        await uploadImport({
            _import: _import, permission: DEFAULT_PERMISSION_WITHOUT_ROLE_MODEL_V2, cacheDriver: cacheDriver
        });
        actualManifestState[_import.alias] = reloadStart;
    } else {
        logger.info(() => `skip update manifest with alias '${_import.alias}' because actual time (${actualTimeManifest}) >= expected time (${expectTimeManifest})`);
    }
} else {
    // иначе грузим все манифесты с указанными доменами
    for (let _import of rootData.imports) {
        const expectTimeManifest = await clusterCache.getExpectTimeManifest(_import.alias);
        const actualTimeManifest = actualManifestState[_import.alias];
        if (expectTimeManifest > actualTimeManifest) {
            await uploadImport({
                _import: _import, cacheDriver: cacheDriver
            });
            actualManifestState[_import.alias] = reloadStart;
        } else {
            logger.debug(() => `skip update manifest with alias ${_import.alias} because actual time (${actualTimeManifest}) >= expected time (${expectTimeManifest})`);
        }
    }
}
//удалим из actualManifestState те манифесты, которых нет в root manifest
const rootAlias = rootData.imports.map(el => el.alias);
for (let alias in actualManifestState) {
    if (!rootAlias.includes(alias)) {
        delete actualManifestState[alias];
        await cacheDriver.del(CLUSTER_MANIFEST_UPDATE_TIME_KEY + `${alias}`);
    }
}
await clusterCache.saveActualManifestTimes(actualManifestState);
//удаляем старые манифесты
await removeOldManifests(rootData);
process.exitCode = 0;

const endLoadTime = Date.now();
logger.debug(() => `send success post message with endLoadTime ${endLoadTime}`);
logger.info(() => `Load ${countImportsInRoot} manifests took ${endLoadTime - reloadStart} ms`);
parentPort.postMessage({ status: 'success', endLoadTime: endLoadTime });
await clusterCache.close();
logger.debug(() => 'Connection to cache closed after load manifest');

/**
 * Проверяем, что в манифесте нет дубликатов доменов. Если дубликаты есть, то кидаем ошибку
 */
function throwIfPermissionDuplicates(rootData) {
    let sourcePermissionsArray = rootData.imports.map(el => el.permission.toLowerCase());
    const counts = {};
    for (const item of sourcePermissionsArray) {
        counts[item] = (counts[item] || 0) + 1;
    }
    const duplicateOfPermission= Object.keys(counts).filter(key => counts[key] > 1);
    if (duplicateOfPermission.length > 0) {
        throw Error(`The root manifest contains a list of imports with duplicate permissions (${duplicateOfPermission}). The duplicate must be removed.`);
    }
}

/**
 * Переводим все permission в нижний регистр, чтобы они везде были одинаковые
 */
function convertPermissionToLowerCase(data) {
    return data.map(item => ({
        ...item,
        permission: item.permission.toLowerCase()
    }));
}

async function uploadImport({_import, permission = _import.permission, cacheDriver}) {
    const manifestMetaCacheKey = CLUSTER_MANIFEST_META + `${permission}`;
    const manifestMeta = JSON.parse(await cacheDriver.get(manifestMetaCacheKey)) || {};
    logger.info(() => [
        `Start loading manifest start with permission ${permission}`,
        {title: 'import element', obj: _import}
    ]);
    try {
        const foolRootFilePath = makeURIByBaseURI(_import.root, parentFile);
        const result = await storeManager.reloadManifest(foolRootFilePath);
        result.permission = permission;
        result.warmupNeeded = _import.warmupNeeded || false;
        logger.debug(() => `storeManager.reloadManifest with import ${permission} in manifest loader is finished`);

        const storage = await storeManager.applyManifest(result, true, true, manifestMeta);
        logger.debug(() => `storeManager.applyManifest with import ${permission} finish success`);

        logger.info(() => `Manifest with permission ${permission}. Old hash ${manifestMeta.manifestHash}, new hash ${storage.hash}`);
        if (manifestMeta.manifestHash !== storage.hash) {
            const parser = storage.parser;
            delete parser.manifest;
            await cacheDriver.setGuaranteed(CLUSTER_MANIFEST_PARSER + `${permission}`, JSON.stringify(parser));

            delete storage.parser;
            delete storage.mergeMap;
            await cacheDriver.setGuaranteed(CLUSTER_MANIFEST + `${permission}`, JSON.stringify(storage));

            manifestMeta.successLoadTimestamp = Date.now();
            manifestMeta.permission = permission;
            manifestMeta.manifestHash = storage.hash;
            manifestMeta.datasetHash = storage.datasetHash;
            delete manifestMeta.error;
            logger.info(() => `Manifest loader successfully set manifest to cache: ${permission}`);
        } else {
            logger.info(() => `Manifest with ${permission} not changed. Just update manifestMeta.tsVersion.`);
        }
        manifestMeta.tsVersion = reloadStart;
    } catch (error) {
        const errorMessage = `${uuidv4()}: Manifest loader failed to set manifest. ${error.message}`;
        manifestMeta.error = errorMessage;
        manifestMeta.errorLoadTimestamp = Date.now();
        manifestMeta.tsVersion = reloadStart;
        logger.error(() => errorMessage, error);
    }
    await cacheDriver.setGuaranteed(manifestMetaCacheKey, JSON.stringify(manifestMeta));
}

/**
 * Удаление из кеша манифестов, которых нет в rootData. То есть они были удалены из текущего рут манифеста
 * @param rootData - текущий рут манифест
 */
async function removeOldManifests(rootData) {
    // эта конструкция нужна, чтобы проверить и удалить все следы манифеста, если вдруг 1 или 2 уже были удалены
    // так мы вытаскиваем все следы и удаляем в любом случае все
    const permissionsInCache = new Set([
        ...(await getPermissionFromCache(CLUSTER_MANIFEST)),
        ...(await getPermissionFromCache(CLUSTER_MANIFEST_META)),
        ...(await getPermissionFromCache(CLUSTER_MANIFEST_PARSER))
        ]);

    if (permissionsInCache.size === 0) {
        logger.info(() => `in cache no one manifest (keys with ${CLUSTER_MANIFEST} or ${CLUSTER_MANIFEST_PARSER} prefix)`);
        return;
    }

    let permissionInRoot = rootData.imports.map(el => el.permission);
    if (!isV2RolesEnabled) {
        logger.info(() => `Role mode 2 is disabled, so we don't check against the actual permissions array, but replace it with the default permission '${DEFAULT_PERMISSION_WITHOUT_ROLE_MODEL_V2}'`);
        permissionInRoot = [DEFAULT_PERMISSION_WITHOUT_ROLE_MODEL_V2];
    }
    const manifestPermissionForRemove = [];
    for (const permission of permissionsInCache) {
        const isExist = permissionInRoot.find(el => el === permission);
        if (!isExist) {
            manifestPermissionForRemove.push(permission);
        }
    }
    if (manifestPermissionForRemove.length === 0) {
        logger.info(() => 'all of manifest contains in current rootData, nothing to remove');
        return;
    }

    for (const permission of manifestPermissionForRemove) {
        logger.debug(() => `delete manifest ${permission} from cache`);
        await cacheDriver.del(CLUSTER_MANIFEST_PARSER + `${permission}`);
        await cacheDriver.del(CLUSTER_MANIFEST + `${permission}`);
        await cacheDriver.del(CLUSTER_MANIFEST_META + `${permission}`);
    }
    logger.info(() => `removed ${manifestPermissionForRemove.length} old manifest `);
}

/**
 * Получить список прав из кеша по ключу.
 * Ищем в кеше все элементы по префиксу, и удаляем сам префикс.
 * В данном файле этот метод нужен для поиска прав манифестов в кеше
 * @param keyPrefix - префикс для поиска
 */
async function getPermissionFromCache(keyPrefix) {
    const keyPrefixLength = keyPrefix.length;
    const keyPrefixEscaped = keyPrefix.replace(/_/g, '\\_');
    const arrayFromCache = await cacheDriver.getKeysLike(keyPrefixEscaped);
    if (!Array.isArray(arrayFromCache)) {
        return [];
    }
    return arrayFromCache.map(str => str.slice(keyPrefixLength));

}

