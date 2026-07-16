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
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber

  Contributors:
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
*/

import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import objectHash from 'object-hash';
import {ImportByPermissionAndAliasMap} from '@back/helpers/import-by-permission-and-alias-map.mjs';

let manifestByPermission = new Map();
let joinManifests = new Map();
let permissionByAlias = ImportByPermissionAndAliasMap.createEmpty();

const logger = getLoggerWithTag('manifestHolder.js');


/**
 * @returns {string}
 */
export function getPermissionByAlias(alias) {
    return permissionByAlias.getByAlias(alias)?.permission;
}

/**
 * @returns {string}
 */
export function getAliasByPermission(permission) {
    return permissionByAlias.getByPermission(permission)?.alias;
}

/**
 * @returns {object}
 */
export function getImportByPermission(permission) {
    return permissionByAlias.getByPermission(permission);
}

/**
 * @returns {object}
 */
export function getImportByAlias(alias) {
    return permissionByAlias.getByAlias(alias);
}

export function isPermissionByAliasEmpty() {
    return permissionByAlias.size() === 0;
}

async function initPermissionByAliasMap(cache) {
    const rootManifestData = await cache.getRootManifestData();
    if (!rootManifestData) {
        logger.warn(() => 'invoke cache.getRootManifestData return null or empty, app not see root manifest in cache, set permissionByAlias as empty map');
        permissionByAlias = ImportByPermissionAndAliasMap.createEmpty();
        return;
    }
    const imports = rootManifestData?.imports;
    if (!imports) {
        logger.warn(() => 'root manifest in cache not contains imports attribute, set permissionByAlias as empty map');
        permissionByAlias = ImportByPermissionAndAliasMap.createEmpty();
        return;
    }
    if (!Array.isArray(imports)) {
        logger.warn(() => 'root manifest in cache contains imports, but it is not array, set permissionByAlias as empty map');
        permissionByAlias = ImportByPermissionAndAliasMap.createEmpty();
        return;
    }

    permissionByAlias = new ImportByPermissionAndAliasMap(imports);
    logger.trace(() => [
        'permissionByAlias map value',
        {title: 'permissionByAlias', obj: permissionByAlias}
    ]);
}

export function pushManifest(permission, manifest) {
    logger.trace(() => `Pushed manifest ${permission} -> ${JSON.stringify(manifest).substring(0, 100)}`);
    manifestByPermission.set(permission, manifest);
}

function mergeDeep(target, sources) {
    function isObject(item) {
        return (item && typeof item === 'object' && !Array.isArray(item));
    }

    if (!sources.length) return target;
    const source = sources.shift();

    if (isObject(target) && isObject(source)) {
        for (const key in source) {
            if (isObject(source[key])) {
                if (!target[key]) Object.assign(target, { [key]: {} });
                mergeDeep(target[key], [source[key]]);
            } else {
                Object.assign(target, { [key]: source[key] });
            }
        }
    }
    return mergeDeep(target, sources);
}

export function getManifest(permissions) {
    let manifest;
    let countMerge = 0;
    let filteredPermission;
    if (!permissions || permissions.length < 1 ) {
        filteredPermission = [...manifestByPermission.keys()];
    } else {
        filteredPermission = permissions.filter(permission => Boolean(manifestByPermission.get(permission)));
    }

    logger.trace(() => [
        'after filter keys by exist permission in manifestByDomain',
        {title: 'permissions', obj: permissions},
        {title: 'filteredPermission', obj: filteredPermission},
        {title: 'manifestByPermission.keys', obj: [...manifestByPermission.keys()]}
    ]);

    if (filteredPermission.length === 1) {
        logger.trace(() => `return manifest by permission ${filteredPermission[0]}`);
        return manifestByPermission.get(filteredPermission[0]);
    }
    // Фильтруем ключи, которых нет в списке манифеста, т.к. среди прав могут быть права других сервисов.
    // Т.к. мы кешируем манифест
    if (!filteredPermission || filteredPermission.length === 0) {
        logger.debug(() => 'after filter permission by exist keys in manifestByPermission, filteredPermission array is empty, check in \'trace\' log level');
        return undefined;
    }
    const joinPermission = filteredPermission.join('|');
    logger.trace(() => `after filter permission by exist manifest, it contains only ${joinPermission}`);
    const cachedManifest = joinManifests.get(Symbol.for(joinPermission))?.deref();
    if (cachedManifest) {
        logger.trace(() => `find manifest by permission ${joinPermission} in local weakref cache`);
        return cachedManifest;
    }

    for (const permission of filteredPermission) {
        const manifestByDomainElement = manifestByPermission.get(permission);
        logger.trace(() => `fullObjByKey with permission ${permission} exist? = ${Boolean(manifestByDomainElement)}`);
        if (manifestByDomainElement) {
            if (manifest) {
                countMerge++;
                logger.trace(() => `merge ${permission} into manifest, countMerge = ${countMerge}`);
                mergeDeep(manifest, [manifestByDomainElement]);
            } else {
                manifest = mergeDeep({}, [manifestByDomainElement]);
            }
        }
    }

    logger.trace(() => `countMerger after merge all manifest = ${countMerge}`);

    if (countMerge > 0) {
        let manifestHash = objectHash(manifest.manifest);
        manifest.manifestHash = manifestHash;
        manifest.hash = manifestHash;
        manifest._joinManifest = true;
        logger.trace(() => `merge ${countMerge+1} manifests by permission ${joinPermission} new hash = ${manifestHash} and delete permission`);
        manifest.permission = `__manifest_joins_${countMerge}`;
        // eslint-disable-next-line no-undef
        joinManifests.set(Symbol.for(joinPermission), new WeakRef(manifest));
    }
    return manifest;
}

export function checkAllKeys(permissions) {
    if (!permissions) {
        return [];
    }
    return permissions.filter(item => !manifestByPermission.has(item));
}

export async function invalidateManifestHolderCache(clusterCache) {
    logger.debug(() => 'invalidate ManifestHolder cache');
    manifestByPermission = new Map();
    await initPermissionByAliasMap(clusterCache);
    joinManifests = new Map();
}
