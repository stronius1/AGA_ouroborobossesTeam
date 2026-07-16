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
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2025
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2025
*/

import './helpers/env.mjs';
import express from 'express';
import middlewareCompression from './middlewares/compression.mjs';
import controllerStatic from './controllers/static.mjs';
import controllerCore from './controllers/core.mjs';
import controllerSearch from './controllers/search.mjs';
import controllerStorage from './controllers/storage.mjs';
import controllerEntity from './controllers/entity.mjs';
import controllerGigachat from './controllers/gigachat.js';
import middlewareAccess from './middlewares/access.mjs';
import middlewareHeaders from './middlewares/headers.mjs';
import middlewareManifest from './middlewares/manifestFromCache.mjs';
import parseTokenMiddleware from './middlewares/parseTokenMiddleware.mjs';
import manifestReloadController from './cluster/controller/manifest-reload.controller.mjs';
import aboutAliasController from './cluster/controller/about-alias.controller.mjs';
import cluster from 'node:cluster';
import {Worker} from 'node:worker_threads';
import { ClusterCache } from './cluster/cache.mjs';
import cache from '@back/storage/cache.mjs';
import perfRecorder from './utils/logger/perf-recorder.mjs';
import {CLUSTER_MASTER_COMMAND, NodeStatus} from './cluster/constants.mjs';
import {changeLoggerImpl, getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import {mainLogger} from '@back/utils/logger/constLoggers.mjs';
import { registerJsonataVersionFunction } from './helpers/jsonata/versionsFunc.mjs';
import os from 'os';
import { v4 as uuidv4 } from 'uuid';
import getInfoResponse from './utils/getInfoResponse.mjs';
import {invalidateManifestHolderCache} from '@back/storage/manifestHolder.mjs';
import controllerLogger from '@back/controllers/logger.mjs';
import userRightsController from '@back/cluster/controller/user-rights.controller.mjs';

const CHECK_CLUSTER_STATUS_INTERVAL = 5000;
const READY_STATUS_SUCCESS = {code: 200, message: {status: 'ready', source: 'const'}};

const MESSAGE_TYPES = {
    WORKER_STATUS: 'worker_status',
    MANIFEST: 'manifest',
    MANIFEST_RELOAD: 'manifest_reload',
    PRIMARY_ID: 'primary_id',
    READYZ: 'readyz'
};

const WORKER_STATUS = {
    LOADING: 'workerLoading',
    READY: 'workerReady'
};

changeLoggerImpl(mainLogger);
const LOG_TAG = 'cluster';
const logger = getLoggerWithTag(LOG_TAG);

if (global.$logger.profileEnable) perfRecorder.start();

const processId = `${uuidv4().split('-')[0]}@${os.hostname()}`;
let primaryProcessId;

// Флаг для обозначения процесса удаления, чтобы пропускать какие-нибудь операции, пока удаление в процессе
let clearCacheInProgress = false;

const clusterCache = new ClusterCache();
await clusterCache.init();
const cacheDriver = await clusterCache.getClusterCache();

/**
 * Запускает нового воркера. workerStatusRegistry служит для отслеживания состояния запуска воркеров
 * для своевременной раздачи манифеста в ведомых подах. Если передан manifestHash, хеш будет передан в воркер
 * по окончании его запуска.
 * @param {Cluster} cluster экземпляр nodejs cluster
 * @param {Object<number, string>} workerStatusRegistry хранилище статусов воркеров
 * @param {string} [manifestEndLoadTime = null] хеш манифеста для нового воркера
 * @param {Object} [readyzStatus = null] ответ для ready пробы
 */
function startWorker(cluster, workerStatusRegistry, manifestEndLoadTime = null, readyzStatus = null) {
    // Пришлось переопределить переменную окружения в текущем процессе. Переданные через options env игнорировались.
    // const workerNodeEnv = Object.assign({}, process.env, { 'NODE_OPTIONS' : process.env.VUE_APP_DOCHUB_CLUSTER_NODE_PARAMS_WORKER });
    process.env.NODE_OPTIONS = process.env.VUE_APP_DOCHUB_CLUSTER_NODE_PARAMS_WORKER;
    const newWorker = cluster.fork();
    workerStatusRegistry[newWorker.id] = WORKER_STATUS.LOADING;
    newWorker.on('message', (message) => {
        if (message.type === MESSAGE_TYPES.WORKER_STATUS) {
            workerStatusRegistry[newWorker.id] = message.data;
            if (message.data === WORKER_STATUS.READY) {
                newWorker.send({ type: MESSAGE_TYPES.PRIMARY_ID, data: processId });
                if (manifestEndLoadTime) {
                    newWorker.send({ type: MESSAGE_TYPES.MANIFEST, data: manifestEndLoadTime });
                }
                if (readyzStatus) {
                    newWorker.send({type: MESSAGE_TYPES.READYZ, data: readyzStatus});
                }
            }
        }
    });
}

async function _checkImMaster() {
    const status = await clusterCache.status(processId);
    const masterId = status.info?.id;
    if (masterId === processId) {
        logger.info(() => `[myId ${processId}, masterId ${masterId}]: I'm a master node`);
    } else {
        logger.info(() => `[myId ${processId}, masterId ${masterId}]: I'm NOT a master node`);
    }
}

async function initControllers(app) {
    // API ядра
    controllerCore(app);

    controllerSearch(app);

    // API сущностей
    controllerEntity(app);

    // Контроллер доступа к файлам в хранилище
    controllerStorage(app);

    // Контроллер логирования
    controllerLogger(app);

    // GigaChat
    await controllerGigachat(app);

    // Статические ресурсы
    controllerStatic(app);

    registerJsonataVersionFunction();
}

function startClusterWorker(app, serverPort, clusterCache) {
    // Актуальный манифест
    app.storage = null;
    parseTokenMiddleware(app);
    middlewareAccess(app);
    middlewareHeaders(app);
    middlewareCompression(app);
    middlewareManifest(app, clusterCache);

    manifestReloadController(app, clusterCache);
    aboutAliasController(app, clusterCache);
    userRightsController(app);

    app.get('/health', async(req, res) => {
        const commandState = await clusterCache?.getCommandState();
        return commandState
            ? res.status(200).json({ status: commandState })
            : res.status(503).json({ status: 'Not ready' });
    });

    app.get('/health/info', async(req, res) => {

        if (!primaryProcessId) return res.status(503).json({ message: 'No info, did not receive primary process id yet.' });
        const primaryState = await clusterCache?.getInfoProbeState(primaryProcessId);
        if (!primaryState) return res.status(503).json({
            primaryProcessId: primaryProcessId,
            message: 'Cannot read pod state info from clusterCache.'
        });
        const output = {
            self: getInfoResponse(primaryState)
        };
        const status = await clusterCache.status(processId);
        const masterId = status.info?.id;
        if (primaryProcessId !== masterId) {
            const masterState = await clusterCache?.getInfoProbeState(masterId);
            if (!masterState) {
                return res.status(503).json({
                    masterId: masterId,
                    primaryProcessId: primaryProcessId,
                    message: 'Cannot read master state info from clusterCache.'
                });
            }
            output.master = getInfoResponse(masterState);
        } else {
            output.master = output.self;
        }

        output.manifests = (await clusterCache.getAllManifestState()).map(el => {
            if (el.successLoadTimestamp) {
                el.successLoadTimestampISO = new Date(el.successLoadTimestamp).toISOString();
            }
            if (el.errorLoadTimestamp) {
                el.errorLoadTimestampISO = new Date(el.errorLoadTimestamp).toISOString();
            }
            return el;
        });
        return res.status(200).json(output);
    });

    // Проба readiness
    app.get('/health/readyz', async(req, res) => {
        if (app.readyz) {
            return res.status(app.readyz.code).json(app.readyz.message);
        }
        logger.info(() => 'app.readyz is empty, return state from cache, readyz must be in app');
        const commandState = await clusterCache?.getCommandState();
        return commandState !== 'ready'
            ? res.status(503).json({ status: commandState })
            : res.status(200).json({ status: 'ready' });
    });

    // Запуск сервера
    const server = app.listen(serverPort, function() {
        logger.info(() => `Cluster fork ${process.pid} running on ${serverPort}`);
    });

    server.setTimeout(500000);
}

if (cluster.isPrimary) {
    primaryProcessId = processId;
    let livenessWorker;
    const clusterState = {
        state: {
            primaryProcessId,
            launchTimestamp: Date.now(),
            status: 'loading',
            messageCurrent: 'Cluster is loading',
            lastSuccessfulReloadTimestamp: null,
            lastReloadTimestamp: null
        },
        update(values = {}) {
            Object.assign(this.state, values);
            livenessWorker?.postMessage(this.state.status);
            clusterCache.setInfoProbeState(this.state, primaryProcessId);
        }
    };

    logger.info(() => `Master node in nodeJs with pid=${process.pid} on processId=${processId} is running`);
    logger.info(() => `Primary process node params: ${process.execArgv}; and options: ${process.env.NODE_OPTIONS}`);


    const noRequestsOnLoading = (process.env.VUE_APP_DOCHUB_CLUSTER_NO_REQUESTS_ON_LOADING || 'off') === 'on';

    const livenessNodeEnv = Object.assign({}, process.env, { 'NODE_OPTIONS' : process.env.VUE_APP_DOCHUB_CLUSTER_NODE_PARAMS_LIVENESS });
    let startLivenessWorker = () => livenessWorker =
        new Worker('./src/backend/cluster/liveness.mjs', {
            env: livenessNodeEnv,
            execArgv: ['--import', './src/backend/cluster/register-hooks.mjs']
        });
    startLivenessWorker();
    clusterState.update();
    livenessWorker.on('exit', (code) => {
        logger.warn(() => `Liveness worker died with code: ${code}. Restarting...`);
        startLivenessWorker();
        clusterState.update();
    });

    let manifestEndLoadTime = null;
    // статус нужен чтобы передать его новому воркеру если старый умирает
    let readyzStatus = null;

    const spreadManifest = function(manifestEndLoadTime) {
        for (const id in cluster.workers) {
            cluster.workers[id].send({type: MESSAGE_TYPES.MANIFEST, data: manifestEndLoadTime});
        }
        logger.debug(() => 'Spreading manifest to workers');
    };

    const spreadReadyz = function(status) {
        if (!noRequestsOnLoading)
            return;
        readyzStatus = status;
        for (const id in cluster.workers) {
            logger.debug(() => `Spreading manifest to worker ${id}`);
            cluster.workers[id].send({type: MESSAGE_TYPES.READYZ, data: status});
        }
        logger.debug(() => [{ title: 'Spreading readyz to workers finished', obj: status}]);
    };

    const workerStatusRegistry = {};

    const clusterForksRaw = process.env.VUE_APP_DOCHUB_CLUSTER_FORKS;
    const clusterForksNumber = parseInt(clusterForksRaw);
    if (isNaN(clusterForksNumber) || clusterForksNumber <= 0) {
        logger.warn(() => 'Cluster forks = 0, servers for receiving requests are not running! ' +
            'To start them, you need to specify a variable "VUE_APP_DOCHUB_CLUSTER_FORKS=(number)" in the environment. ' +
            `Current value ${clusterForksRaw}`);
    } else {
        logger.info(() => `Cluster forks: ${clusterForksNumber}`);
        for (let i = 0; i < clusterForksNumber; i++) {
            startWorker(cluster, workerStatusRegistry);
        }
    }

    // Пробуем перезапустить рабочие воркеры, если они отвалились.
    cluster.on('exit', (worker) => {
        logger.warn( () => `Worker ${worker.process.pid} died, restarting`);
        delete workerStatusRegistry[worker.id];
        startWorker(cluster, workerStatusRegistry, manifestEndLoadTime, readyzStatus);
    });

    let isLoading = false;
    // Загружаем манифест в отдельном потоке
    const loadManifest = () => {
        if (isLoading) {
            logger.info(() => 'Manifest is loading');
            return;
        }

        clusterState.update({
            status: 'loading',
            messageCurrent: 'Loading manifest'
        });

        const manifestLoaderNodeEnv = Object.assign({}, process.env, { 'NODE_OPTIONS' : process.env.VUE_APP_DOCHUB_CLUSTER_NODE_PARAMS_RELOAD });
        const manifestLoader = new Worker('./src/backend/cluster/manifest-loader.mjs', {
            env: manifestLoaderNodeEnv,
            execArgv: ['--import', './src/backend/cluster/register-hooks.mjs']
        });
        isLoading = true;
        clusterCache.updateCommandState('loading manifest');
        spreadReadyz({code: 503, message: {status: 'Loading manifest'}});

        manifestLoader.once('message', async(result) => {
            logger.debug(() => [{ title: 'accept message from manifestLoader with data', obj: result }]);
            if (result?.status === 'success') {
                setTimeout(() => {
                    isLoading = false;
                    clusterCache.updateCommandState('ready');
                }, CHECK_CLUSTER_STATUS_INTERVAL * 2);

                manifestEndLoadTime = result.endLoadTime;
                clusterCache.initializeManifest(manifestEndLoadTime);
                spreadManifest(manifestEndLoadTime);
                const timestamp = Date.now();
                const newState = {
                    status: 'ready',
                    messageCurrent: 'Manifest load finish',
                    lastSuccessfulReloadTimestamp: timestamp,
                    lastReloadTimestamp: manifestEndLoadTime,
                    lastHashChange: manifestEndLoadTime
                };

                clusterState.update(newState);
                spreadReadyz(READY_STATUS_SUCCESS);
                clearCacheInProgress = true;
                await clusterCache.clearCache();
                clearCacheInProgress = false;
            }
            if (result.error) {
                logger.error(() => `Error reported in manifest loader: ${result.error}`);
            }
        });
        manifestLoader.on('exit', (code) => {
            logger.info(() => `Manifest loading exited with code ${code}`);
            if (code !== 0) {
                if (manifestEndLoadTime) {
                    logger.error(() => 'Manifest reload attempt failed. Running on the old manifest.');
                    clusterCache.updateCommandState('ready');
                    clusterState.update({
                        status: 'ready',
                        messageCurrent: 'Manifest reload failed, running on the old manifest',
                        lastReloadTimestamp: Date.now(),
                        lastReloadSuccess: false
                    });
                    spreadReadyz(READY_STATUS_SUCCESS);
                    isLoading = false;
                } else {
                    logger.error(() => 'Manifest loading failed (manifestEndLoadTime is undefined). Exiting.');
                    process.exit(1);
                }
            }
        });
    };

    void _checkImMaster();

    setInterval(async() => {
        const status = await clusterCache.status(processId);
        const masterId = status.info?.id;
        switch (status.status) {
            case NodeStatus.MASTER: {// Под выполняющий код является или стал мастером
                const command = await cacheDriver.get(CLUSTER_MASTER_COMMAND);
                if (command === MESSAGE_TYPES.MANIFEST_RELOAD && !clearCacheInProgress) { // При наличии команды на перезагрузку и не запущена очистка кеша - запускаем перезагрузку манифеста
                    await cacheDriver.del(CLUSTER_MASTER_COMMAND);
                    logger.info(() => `[myId ${processId}, masterId ${masterId}]: Get manifest_reload command and start reload`);
                    loadManifest();
                } else if (clearCacheInProgress) {
                    logger.info(() => `[myId ${processId}, masterId ${masterId}]: Get manifest_reload command but not exec. wait clear cache process finish. Reload start later`);
                }
                if (status.endLoadTime && status.endLoadTime !== manifestEndLoadTime) {
                    await invalidateManifestHolderCache(clusterCache);
                    await cache.clearMemoryCache();
                    spreadManifest(manifestEndLoadTime);
                    spreadReadyz(READY_STATUS_SUCCESS);
                    manifestEndLoadTime = status.info.endLoadTime;
                }
                break;
            }
            case NodeStatus.SLAVE: // Под выполняющий код не мастер, он реплика
                if (status.endLoadTime && status.endLoadTime !== manifestEndLoadTime) { // если в статусе мастера указано время загрузки манифеста и оно отличается от локального
                    if (!Object.keys(workerStatusRegistry).length || Object.values(workerStatusRegistry).some((value) => value !== WORKER_STATUS.READY)) {
                        logger.info( () =>
                            `[myId ${processId}, masterId ${masterId}]: Slave. Not all forks started, skipping this update, and waiting for the next one`
                        );
                        break;
                    }
                    logger.info( () => `[myId ${processId}, masterId ${masterId}]: Slave. Master endLoadTime update. Sync. endLoadTime=${status.endLoadTime}`);
                    manifestEndLoadTime = status.info.endLoadTime;
                    await invalidateManifestHolderCache(clusterCache);
                    await cache.clearMemoryCache();
                    if (manifestEndLoadTime) {
                        spreadManifest(manifestEndLoadTime);
                        spreadReadyz(READY_STATUS_SUCCESS);
                        const timestamp = Date.now();
                        clusterState.update({
                            status: 'ready',
                            messageCurrent: 'Slave, manifest loaded from cache',
                            lastSuccessfulReloadTimestamp: timestamp,
                            lastReloadTimestamp: manifestEndLoadTime,
                            lastReloadSuccess: true
                        });
                    }
                }
                break;
            case NodeStatus.WAIT: // под, будучи мастером или репликой просто ждет и повторит запрос статуса позднее
                if (processId === masterId) {
                    logger.info(() => `[myId ${processId}, masterId ${masterId}]: Waiting for my main thread to finish working`);
                } else {
                    logger.info(() => `[myId ${processId}, masterId ${masterId}]: I'm waiting for the master server to finish its work.`);
                }
                break;
            case NodeStatus.NOT_CONNECTED_TO_CACHE: // Под потерял соединение с кешем (отдельный статус, когда не смогли даже состояние кластера получить)
                logger.warn(() => `[myId ${processId}, masterId ${masterId}]: connect to cache failed. Repeat check after ${CHECK_CLUSTER_STATUS_INTERVAL} ms`);
                break;
            case NodeStatus.NO_MANIFEST: // Под стал мастером (второй этап, после 2 ожиданий никто не захватил метку мастера и текущий утвержден как мастер)
                if (manifestEndLoadTime) { // на этом поде есть данные по прошлому манифесту
                    logger.info(() => `[myId ${processId}, masterId ${masterId}]: processing 'NO_MANIFEST' node status, current manifestEndLoadTime = ${manifestEndLoadTime}, initialize it`);
                    clusterCache.initializeManifest(manifestEndLoadTime);
                    clusterCache.updateCommandState('ready');
                    spreadReadyz(READY_STATUS_SUCCESS);
                } else { // на этом поде не было загружено данных по манифесту
                    logger.info(() => `[myId ${processId}, masterId ${masterId}]: processing 'NO_MANIFEST' node status, current manifestEndLoadTime null, start load manifest`);
                    loadManifest();
                }
                break;
            default:
                logger.warn(() => `[myId ${processId}, masterId ${masterId}]: Unknown cache status: ${status.status}`);
        }
    }, CHECK_CLUSTER_STATUS_INTERVAL);

    // Обрабатываем команду на загрузку манифеста
    cluster.on('message', async(worker, message) => {
       if(message.type === MESSAGE_TYPES.MANIFEST_RELOAD) {
           const commandState = await clusterCache.getCommandState();
           if (commandState === 'ready' || commandState === 'error') {
               await clusterCache.setCommand('manifest_reload');
               clusterState.update({
                   messageCurrent: `${MESSAGE_TYPES.MANIFEST_RELOAD} command received and set to cache at ${new Date().toISOString()}`
               });
           } else {
               logger.error(() => `manifest_reload command ignored because cluster command state not ready or error, actual state ${commandState}`);
           }
       }
    });

} else {

    logger.info(() => `Worker process node params: ${process.execArgv}; and options: ${process.env.NODE_OPTIONS}`);

    const app = express();
    app.isCluster = true;
    app.isReady = true; // в кластерном режиме эту проверку осуществляет readyz
    app.use(express.json());
    const serverPort = process.env.VUE_APP_DOCHUB_BACKEND_PORT || 3030;

    startClusterWorker(app, serverPort, clusterCache);
    await initControllers(app);

    process.on('message', async(message) => {
        switch (message.type) {
            case MESSAGE_TYPES.PRIMARY_ID: {
                logger.info(() => [
                    'accept message PRIMARY_ID',
                    {title: 'data', obj: message.data}
                ]);
                primaryProcessId = message.data;
                break;
            }
            case MESSAGE_TYPES.MANIFEST: {
                logger.info(() => 'accept message MANIFEST with data');
                await invalidateManifestHolderCache(clusterCache);
                await cache.clearMemoryCache();
                break;
            }
            case MESSAGE_TYPES.READYZ:
                logger.info(() => [
                    'accept message READYZ',
                    {title: 'data', obj: message.data}
                ]);
                app.readyz = message.data;
                break;
            default:
                logger.warn(() => `Unknown message type ${message.type}`);
        }
    });


    logger.info(() => `Worker ${process.pid} started`);
    process.send({ type: MESSAGE_TYPES.WORKER_STATUS, data: WORKER_STATUS.READY });
}
