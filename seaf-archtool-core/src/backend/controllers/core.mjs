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
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025, 2026
	  R.Piontik <r.piontik@mail.ru> - 2024
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2024
      Vladislav Nefedov <clay.zenx@gmail.com>, Sber - 2025
      Temnyakov Nikolay <temnjakovn@gmail.com>, Sber - 2024, 2025
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2025
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
      Vladislav Markin, Sber - 2026
*/

import {v4 as uuidv4} from 'uuid';
import datasets from '../helpers/datasets.mjs';
import jsonata from '../helpers/jsonata.mjs';
import storeManager from '../storage/manager.mjs';
import cache from '../storage/cache.mjs';
import queries from '../../global/jsonata/queries.mjs';
import helpers from './helpers.mjs';
import compression from '../../global/compress/compress.mjs';
import dataRequest from '../helpers/request.mjs';
import {isRolesMode} from '../utils/roles.mjs';
import {commitToBitbucket} from '../helpers/bitbucketCommit.mjs';
import {checkRepositoryAPI} from '../middlewares/checkRepositoryAPI.mjs';
import {buildUserMenu} from '@global/manifest/services/menu-builder.mjs';
import {extractUserData} from '../helpers/account.mjs';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import {getCachePrefixWithDomain} from '@back/helpers/cachePrefixByDomain.mjs';
import {findAnyY, ROLES_MODE_V2_ENABLED, ROLES_MODE_V2_VALUE} from '@back/helpers/env.mjs';
import { createBitbucketCommitData, createLayerUpdateDataByParser, restoreParser, updateManifestInfo, validateAndFormatContent } from '@back/helpers/putContent.mjs';
import { prepareEntitiesData } from '@global/manifest/tools/entitiesSource.mjs';

const compressor = compression();

const LOG_TAG = 'controller-core';
const logger = getLoggerWithTag(LOG_TAG);

export default (app) => {

    // Парсит переданные во внутреннем формате данные
    function parseRequest(req) {
        return {
            query: req.params.query,
            params: req.query?.params ? JSON.parse(req.query?.params) : undefined,
            subject: req.query?.subject ? JSON.parse(req.query?.subject) : undefined,
            baseURI: req.query?.baseuri,
            envelope: req.query?.envelope
        };
    }

    // Получаем тайтл из переменной окружения
    app.get(['/seaf-core/api/title', '/api/title'], (_, res) => {
        res.json({title: process.env.VUE_APP_DOCHUB_TITLE || 'SEAF'});
    });

    const anyRoleModeEnabledFlag = findAnyY([
        global.$roles.MODE,
        ROLES_MODE_V2_VALUE
    ]);

    // Динамическая конфигурация фронта
    app.get(['/seaf-core/api/env-config', '/api/env-config'], (_, res) => {
        res.json(
            {
                clickstreamReportUrl: process.env.VUE_APP_CLICKSTREAM_REPORT_URL,
                clickstreamApiKey: process.env.VUE_APP_CLICKSTREAM_API_KEY,
                roleModeEnabled: anyRoleModeEnabledFlag,
                authorityServer: process.env.VUE_APP_DOCHUB_AUTHORITY_SERVER,
                authorityClientId: process.env.VUE_APP_DOCHUB_AUTHORITY_CLIENT_ID,
                authorityScope: process.env.VUE_APP_DOCHUB_AUTHORITY_SCOPE,
                plantUmlServer: process.env.VUE_APP_PLANTUML_SERVER,
                plantUmlRequestType: process.env.VUE_APP_PLANTUML_REQUEST_TYPE,
                s3CloudUrl: process.env.VUE_APP_DOCHUB_S3_CLOUD_URL,
                usingS3Mode: process.env.VUE_APP_DOCHUB_USING_S3,
                archChooser: app.isCluster && ROLES_MODE_V2_ENABLED // выбор архитектуры доступен только в кластере и с включенной ролевкой v2
            }
        );
    });

    // Выполняет произвольные запросы 
    app.get(['/seaf-core/api/core/storage/jsonata/:query', '/core/storage/jsonata/:query'], async function(req, res) {
        if (!helpers.isServiceReady(app, res)) return;
        const start = Date.now();
        const request = parseRequest(req);
        const query = (request.query.length === 36) && queries.QUERIES[request.query]
            ? `(${queries.makeQuery(queries.QUERIES[request.query], request.params)})`
            : request.query;

        await jsonata.makeJSONataQueryResponse(req.storage,
          query,
          res,
          request.envelope === 'true',
          request.params,
          request.subject,
          req.userProfile?.roleId);

        const end = Date.now();
        logger.info(() => JSON.stringify({
            userName: req.userProfile?.userName,
            time: end - start,
            originalUrl: req.originalUrl
        }));
    });

    if (!app.isCluster) { // этот контроллер работает только в режиме backend, для кластера смотри другой контроллер (cluster.mjs)
        // Запрос на обновление манифеста
        app.put(['/seaf-core/api/core/storage/reload', '/core/storage/reload'], async function(req, res) {
            const traceId = uuidv4();
            const start = Date.now();
            const reloadSecret = req.query.secret;
            if (reloadSecret !== process.env.VUE_APP_DOCHUB_RELOAD_SECRET) {
                res.status(403).json({
                    error: `${traceId}: Error reload secret is not valid [${reloadSecret}]`
                });
            } else {
                try {
                    if (isRolesMode()) {
                        app.storage = {...app.storage, manifests: null};
                    }
                    const oldHash = app.storage.hash; // тут работаем не с req.storage а с app т.к. в режиме backend и манифест точно в app
                    const storage = await storeManager.reloadManifest();
                    storage.warmupNeeded = true;
                    app.storage = await storeManager.applyManifest(storage);
                    await cache.clearCache(oldHash);
                    res.json({message: 'success'});
                    const end = Date.now();
                    logger.info(() => JSON.stringify({
                        userName: req.userProfile?.userName,
                        time: end - start,
                        originalUrl: req.route.path
                    }));
                } catch (e) {
                    logger.error(() => `${traceId}: Error when reload`, e);
                    res.status(400).json({error: `${traceId}: Error when reload`});
                }
            }
        });
    }

    // Выполняет произвольные запросы 
    app.get(['/seaf-core/api/core/storage/release-data-profile/:query', '/core/storage/release-data-profile/:query'], async function(req, res) {
        if (!helpers.isServiceReady(app, res)) return;
        const start = Date.now();

        const request = parseRequest(req);

        let storageManifest = req.storage.manifest;
        let key = {
            path: request.query,
            params: request.params
        };

        if (isRolesMode()) {
            const roleId = req.userProfile.roleId;
            storageManifest = req.storage.manifests[roleId];
            key = {
                path: request.query,
                params: request.params,
                roles: roleId
            };
        }

        const cachePrefix = getCachePrefixWithDomain(req.storage);
        await cache.pullFromDataCache(cachePrefix, JSON.stringify(key), async() => {
            if (request.query.startsWith('/'))
                return await datasets(req.storage, req.userProfile?.roleId).releaseData(request.query, request.params);
            else {
                let profile;
                const params = request.params;
                if (request.query.startsWith('{'))
                    profile = JSON.parse(request.query);
                else
                    profile = JSON.parse(await compressor.decodeBase64(request.query));

                const ds = datasets(req.storage);
                if (profile.$base) {
                    const path = ds.pathResolver(profile.$base);
                    if (!path) {
                        res.status(400).json({
                            error: `Error $base location [${profile.$base}]`
                        });
                        return;
                    }
                    return await ds.getData(path.context, profile, params, path.baseURI);
                }
                if (profile.separateDatasets && typeof profile.origin === 'object') {
                    const origin = await Promise.all(Object.keys(profile.origin).map(async(id) => {
                        return {[id]: await ds.releaseData(`/datasets/${id}`)};
                    }));
                    return await ds.getData(origin, {source: profile.source}, params);
                }
                return await ds.getData(storageManifest, profile, params);
            }
        }, res, request.envelope === 'true').catch((e) => {
            logger.error(() => 'Error of release data', e);
        });
        const end = Date.now();
        logger.info(() => JSON.stringify({
            userName: req.userProfile?.userName,
            time: end - start,
            originalUrl: req.originalUrl
        }));
    });

    // Возвращает главное меню
    app.get(['/seaf-core/api/core/storage/user-menu', '/core/storage/user-menu'], async function(req, res) {
        if (!helpers.isServiceReady(app, res)) return;
        let key = {query: `(${queries.IDS.USER_MENU})`};
        let storageManifest = req.storage.manifest;
        const cachePrefix = getCachePrefixWithDomain(req.storage);
        if (isRolesMode()) {
            key.roleId = req.userProfile.roleId;
            storageManifest = req.storage.manifests[key.roleId];
        }

        await cache.pullFromDataCache(cachePrefix, JSON.stringify(key), async() => {
            const datasetDriver = datasets(req.storage);
            return await buildUserMenu(storageManifest, datasetDriver.jsonataDriver);
        }, res).catch((err) => {
            logger.error(() => `Error while building user menu: ${err}`, err);
        });
    });

    // флаг меняется только с перезапуском, так что вычисляем его один раз
    const enableVersionChecker = process.env.VUE_APP_VERSION_CHECKER_ENABLE !== 'false';
    // Возвращает версии
    app.get(['/seaf-core/api/core/storage/versions', '/core/storage/versions'], async function(req, res) {
        if (!helpers.isServiceReady(app, res)) return;
        res.status(200).json({
            archHash: req.storage.hash,
            coreVersion: process.env.npm_package_version,
            enableChecker: enableVersionChecker
        });
    });

    // Возвращает результат работы валидаторов
    app.get(['/seaf-core/api/core/storage/problems/', '/core/storage/problems/'], async function(req, res) {
        if (!helpers.isServiceReady(app, res)) return;
        const start = Date.now();

        res.json(req.storage.problems || []);
        const end = Date.now();
        logger.info(() => JSON.stringify({
            userName: req.userProfile?.userName,
            time: end - start,
            originalUrl: req.originalUrl
        }));
    });

    // Для списка сущностей возвращает пути к файлам исходников и обновлённые данные, подготовленные для сохранения
    app.post(
        '/seaf-core/api/core/storage/prepare-entities/:hash',
        async function putEntity(req, res) {
            try {
                const entities = req.body.content;
                const options = req.body.options;
                const hash = req.params.hash;

                const frontDefaultPath = options.defaultSource;
                let transformedDefaultPath;
                if (frontDefaultPath) {
                    // To get proper absolute path we will use validateAndFormatContent, but it requires an object.
                    try {
                        const lameStructure = { [frontDefaultPath]: 'blank' };
                        transformedDefaultPath = Object.keys(validateAndFormatContent(lameStructure, req.storage, hash))[0];
                    } catch (e) {
                        logger.error(() => 'prepare-entities was not able to process default path: ' + e.message, e);
                    }
                }
                let parser = req.storage.parser;
                if (!parser) {
                    parser = await restoreParser(req.storage);
                }
                const sourceMap = parser.sourceMap;
                const output = await prepareEntitiesData(entities, dataRequest, logger, { defaultSource: transformedDefaultPath }, sourceMap);
                res.status(200).json(output);
            } catch (e) {
                logger.error(() => 'Unexpected error in prepare-entities', e);
                res.status(500).json({ error: 'Непредвиденная ошибка при обработке списка сущностей' });
            }
        }
    ),

    // Создает коммит в репозитории
    app.post(
        ['/seaf-core/api/core/storage/put-content/:hash', '/core/storage/put-content/:hash'],
        checkRepositoryAPI,
        async function requestBitbucket(req, res) {
            const jsonLog = {
                userName: req.userProfile?.userName,
                originalUrl: req.originalUrl
            };
            const start = Date.now();

            const storage = req.storage;
            const content = req?.body?.content;
            const hash = req?.params?.hash;
            let parser;

            try {
                const validatedContent = validateAndFormatContent(content, storage, hash);
                const bitbucketCommitData = createBitbucketCommitData(validatedContent);
                const layersToUpdate = createLayerUpdateDataByParser(validatedContent);

                const userName =
                    (req.userProfile?.userName && req.userProfile.userName !== 'default')
                        ? req.userProfile?.userName
                        : undefined;

                const userInfo = {
                    name: userName,
                    id: req?.userProfile?.sub
                };

                const commitResult = await commitToBitbucket({...bitbucketCommitData, userInfo});
                if (commitResult.success) {
                    res.status(200).json({commitResult});
                } else {
                    res.status(400).json({commitResult});
                    return;
                }
                jsonLog.time = Date.now() - start;
                jsonLog.message = 'On change: bitbucket repository has been updated';
                logger.info(() => JSON.stringify(jsonLog));
                if(!parser) {
                    parser = await restoreParser(storage);
                }
                await parser.onChange(layersToUpdate);
                await updateManifestInfo(parser, storage);

                jsonLog.time = Date.now() - start;
                jsonLog.message = 'On change: manifest has been changed';
                logger.info(() => JSON.stringify(jsonLog));
            } catch (err) {
                jsonLog.time = Date.now() - start;
                jsonLog.message = err;
                logger.error(() => JSON.stringify(jsonLog), err);
                res.status(err?.response?.status || 500).json({
                        success: false,
                        error: err?.message
                });
            }

        }
    );

    // Получаем информацию о пользователе с учетом конфигурации в .env.
    app.get(['/seaf-core/api/core/user-info', '/core/user-info'], (req, res) => {
        const roleMode = isRolesMode();
        logger.debug(() => `/core/user-info request, roleMode = ${JSON.stringify(roleMode)}`);
        if (roleMode) {
            const payload = req.userProfile.payload;
            if (!payload || Object.keys(payload).length === 0) {
                logger.debug(() => '/core/user-info request roleMode if');
                res.json();
            } else {
                logger.debug(() => '/core/user-info request roleMode else');
                const user = extractUserData(payload);
                res.json({user});
            }
        } else {
            logger.debug(() => '/core/user-info request not roleMode');
            res.status(200).json();
        }
    });

    /**
     * В режиме бекенда возвращаем пустой массив, в режиме бека сервис вызываться не должен,
     * но он описан в openapi и должен отвечать
     */
    if (!app.isCluster) {
        app.get('/seaf-core/api/core/user/rights', async function(req, res) {
            if (!helpers.isServiceReady(app, res)) return;
            res.status(200).json([]);
        });
    }

    /**
     * В режиме бекенда запрос about-alias не нужен, чтобы явно обозначить это возвращаем ошибку
     */
    if (!app.isCluster) {
        app.get('/seaf-core/api/core/about-alias', async function(req, res) {
            if (!helpers.isServiceReady(app, res)) return;
            res.status(500).json({
                error: 'in backend mode url \'about-alias\' not allow'
            });
        });
    }
};

