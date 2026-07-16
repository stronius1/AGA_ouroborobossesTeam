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
      Nikolay Temnyakov <temnjakovn@gmail.com>, Sber

  Contributors:
      Nikolay Temnyakov <temnjakovn@gmail.com>, Sber - 2025
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
*/

import cache from '../storage/cache.mjs';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

const logger = getLoggerWithTag('b/u/roles.mjs');
export const DEFAULT_ROLE = 'default';

let roleManifest;

export async function retrieveRolesManifest() {
    if (roleManifest) {
        return roleManifest;
    }
    const { URI } = global.$roles;
    const url = new URL(URI);
    logger.debug(() => `load role manifest from url ${url.toString()}`);
    roleManifest = await loader(url);
    return roleManifest;
}

export async function getCurrentRoleId(roles) {
    const ids = await getCurrentRoles(roles);
    if(ids.length === 0) return DEFAULT_ROLE;
    if(ids.length > 1){
        logger.info(() => [
            'A user must be assigned only one role in a project. A user can have multiple roles, but only one role can match the role in the role manifest (in a project)',
            {title: 'user roles', obj: roles},
            {title: 'user project roles', obj: ids}
        ]);
        throw Error('User must be assigned by only one role');
    }
    return ids[0];
}

async function getCurrentRoles(roles) {
    if(roles.length === 0) return [];

    const result = [];
    const manifest = await retrieveRolesManifest();

    for(let role in roles) {
        for(let nRole in manifest?.roles) {
            if(roles[role] === nRole) {
                result.push(nRole);
            }
        }
    }
    return result;
}

export const newManifest = (obj, exclude, filters)=> Object.entries(obj)
    .filter(([key, value]) => (typeof value != 'object' || Array.isArray(value) || matchExclude(key, exclude)) || matchRegex(key, filters))
    .reduce((acc, [key, value]) => {
        if(value != null && typeof value === 'object' && !Array.isArray(value)) {
            acc[key] = newManifest(value, exclude, filters);
            return acc;
        }
        return Array.isArray(obj) ?  [...acc, ...obj] : ({...acc, [key]: obj[key]});
    }, {});

export async function loader(uri) {
    const response = await cache.request(uri, '/');
    return response && (typeof response.data === 'object'
        ? response.data
        : JSON.parse(response.data));
}

export function isRolesMode() {
    const {MODE} =  global.$roles;
    return (MODE || 'N').toUpperCase() === 'Y';
}

function matchRegex(string, filters){

    const len = filters.length;

    for (let i = 0; i < len; i++) {
        if (string.match(filters[i])) {
            logger.trace(() => `[matchRegex] build menu element [${string}] = TRUE by filter [${filters[i]}]`);
            return true;
        }
    }
    logger.trace(() => `[matchRegex] build menu element [${string}] = FALSE`);
    return false;
}

function matchExclude(string, exclude) {
    const len = exclude.length;
    for (let i = 0; i < len; i++) {
        if (string === exclude[i]) {
            logger.trace(() => `[matchExclude] build menu element [${string}] = TRUE by filter exclude [${exclude[i]}]`);
            return true;
        }
    }
    logger.trace(() => `[matchExclude] build menu element [${string}] = FALSE`);
    return false;
}




