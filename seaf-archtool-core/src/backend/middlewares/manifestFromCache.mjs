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
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2025
*/

import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import storeManager from '@back/storage/manager.mjs';
import {
    checkAllKeys,
    getManifest, getPermissionByAlias,
    isPermissionByAliasEmpty,
    pushManifest
} from '@back/storage/manifestHolder.mjs';
import {ROLES_MODE_V2_ENABLED} from '@back/helpers/env.mjs';
import {performanceLogger} from '@back/utils/logger/index.mjs';
import {HttpHeaders} from '@global/helpers/httpHeaders.mjs';
import {noNeedManifest} from '@back/helpers/manifestNeedChecker.mjs';
import {getPermissionWithAccess} from '@back/utils/get-user-permission.mjs';

const LOG_TAG = '/b/m/manifestFromCache';
const logger = getLoggerWithTag(LOG_TAG);
const perfLogger = performanceLogger?.getGenericLogger();


/**
 * Добавляем манифест в запрос.
 * Если работаем в режиме кластера, тогда:
 *  - добавляем манифест на основе полученных прав если ролевая модель включена
 *  - добавляем общий манифест если ролевая модель выключена
 * Если работаем в режиме backend, тогда добавляем манифест из app.storage
 * @param app - глобальное пространство
 * @param cache - реализация кеша
 */
export default (app, cache) => {
    async function uploadManifestFromCache(permissions) {
        for (const permission of permissions) {
            const getManifest = await cache.getManifest(permission);
            pushManifest(permission, getManifest);
        }
    }

    // Если запущены в режиме кластера, то проверяем, подходит ли кеш для использования. Если нет - кидаем ошибку
    app.isCluster && throwIfCacheNotValidForUse(cache);

    /**
     * Дополнительная фильтрация если в заголовках запроса передан домен
     * Тогда получится сжать количество требуемых манифестов для запроса до 1, который указан в заголовке.
     * Если домена, который передан в заголовке нет в списке прав, то возвращается пустой массив
     * @param req - запрос
     * @param permissions - список прав пользователя из токена
     * @returns json объект с атрибутами:
     *      success - статус успешна проверка или нет
     *      permission - если проверка успешная, то тут право соответстующее домену из заголовка
     *      message - сообщение об ошибке, если запрос не удачный
     */
    async function filterPermissionByReqDomain(req, permissions) {
        if (!ROLES_MODE_V2_ENABLED) { // если ролевая модель выключена, то манифест один, возвращаем permissions как есть
            return {success: true, permission: permissions};
        }
        const orgCtx = req.headers[HttpHeaders.X_SFA_ORGCTX];
        if (!orgCtx) {
            return {success: false, failStatus: 400, message: `required header ${HttpHeaders.X_SFA_ORGCTX} not found or empty`};
        }
        if (isPermissionByAliasEmpty()) {
            return {success: false, message: 'no data of root manifest, try later, check logs'};
        }
        const permissionFromDomain = getPermissionByAlias(orgCtx);
        let result = permissions?.find(p => p === permissionFromDomain);
        logger.trace(() => [
            'permissions after domain alias filter',
            {title: 'domain(orgCtx from header)', obj: orgCtx},
            {title: 'permission associated by domain', obj: permissionFromDomain},
            {title: 'filter result', obj: result}
        ]);
        if (result) {
            // по результам find у нас либо undefined либо 1 элемент, если он есть, тогда обернем его в массив
            // пока так надо в ожидании доработки по common манифесту (они будут склеиваться возможно)
            // TODO: если про common манифест (ERA-1832) забыли и никто не знает о чем разговор,
            //       то можно переделать на один элемент, но важно и обработку в app.use поправить
            result = [result];
        }
        return {success: true, permission: result};
    }

    app.use(async(req, res, next) => {
        try {
            perfLogger?.setStart();
            if (noNeedManifest(req)) {
                return next();
            }
            if (!app.isCluster) {
                req.storage = app.storage;
            } else {
                let permissions = getPermissionWithAccess(req)
                    ?.map(el => el.rp);
                logger.trace(() => `user jwt permissions = ${permissions}`);
                if (!Array.isArray(permissions) || permissions.length === 0) {
                    logger.debug(() => 'user have no permissions in jwt');
                    res.status(401).json({error: 'no manifest for user permissions (empty permissions)'});
                    return;
                }
                const filterResult = await filterPermissionByReqDomain(req, permissions);
                if (!filterResult.success) {
                    if (filterResult.failStatus) {
                        res.status(filterResult.failStatus)
                            .json({error: filterResult.message});
                    } else {
                        // если проверка прав не удалась, тогда прерываем обработку
                        res.set(HttpHeaders.RETRY_AFTER, '60') // Попробуй через 60 секунд
                            .status(503)
                            .json({error: filterResult.message});
                    }
                    return;
                }
                permissions = filterResult.permission;
                if (!Array.isArray(permissions) || permissions.length === 0) {
                    logger.debug(() => 'user have no permissions after filter by org ctx (no have permission on selected orgctx)');
                    res.status(401).json({error: 'no manifest for user permissions (empty permissions on ctx)'});
                    return;
                }
                const notExistPermissions = checkAllKeys(permissions);
                await uploadManifestFromCache(notExistPermissions);
                let manifest = getManifest(permissions);
                if (!manifest) {
                    logger.debug(() => `no manifest found for permissions ${permissions}`);
                    res.status(401).json({error: 'no manifest for user permissions (not found)'});
                    return;
                } else {
                    req.storage = await storeManager.applyManifest(manifest, true, false);
                    delete req.storage.parser;
                    logger.trace(() => `apply manifest by hash ${manifest.hash}`);
                }
            }
            if (req.storage) {
                next();
            } else {
                res.status(401).json({error: 'access denied'});
            }
        } finally {
            perfLogger?.setEnd();
        }
    });

    /**
     * Для работы этого фильтра нужен кеш, в котором есть функция getManifest
     * Если ее нет, то использовать такой кеш не получится
     * @param cache
     * @returns {boolean}
     */
    function throwIfCacheNotValidForUse(cache) {
        if (!cache || !cache.isClusterCache) {
            throw Error('It\'s impossible to use the passed cache for middleware operation; the required getManifest function is missing. The cache implementation must be modified or it must not be passed.');
        }
    }
};
