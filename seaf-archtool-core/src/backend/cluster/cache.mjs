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
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2024
*/

import postgres from '../drivers/postgres.mjs';
import {
    CLUSTER_ALL_MANIFEST_ACTUAL_TIME_KEY,
    CLUSTER_COMMAND_REFRESH_TIMESTAMP,
    CLUSTER_MANIFEST,
    CLUSTER_MANIFEST_META,
    CLUSTER_MANIFEST_UPDATE_TIME_KEY,
    CLUSTER_MASTER_COMMAND,
    CLUSTER_MASTER_COMMAND_STATE,
    CLUSTER_MASTER_INFO,
    CLUSTER_MASTER_INFO_PROBE, CLUSTER_ROOT_MANIFEST_DATA,
    NodeStatus
} from './constants.mjs';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import {v4 as uuidv4} from 'uuid';

const LOG_TAG = 'cluster-cache';
const logger = getLoggerWithTag(LOG_TAG);

const CLUSTER_MASTER_TIMEOUT = 60000;
const MASTER_SET_CHECK = 2;

const datalakeCacheMode = process.env.VUE_APP_DOCHUB_DATALAKE_CACHE;
let cacheDriver = null;

//редис удален в задаче ERA-1986 03.2026 спустя какое-то время эту проверку можно будет убрать как и остальные упоминания редиса
const redisUnsupportedMessage = `redis cache now not supported, check env VUE_APP_DOCHUB_DATALAKE_CACHE, current value ${datalakeCacheMode}`;

export class ClusterCache {

    isClusterCache = true;

    async updateCommandState(state) {
        try {
            await cacheDriver.setGuaranteed(CLUSTER_MASTER_COMMAND_STATE, state);
        } catch (error) {
            logger.error(() => `Update command state ${state} in cache failed. Error ${error}`);
        }
    }

    async getRootManifestData() {
        try {
            return JSON.parse(await cacheDriver.get(CLUSTER_ROOT_MANIFEST_DATA));
        } catch (error) {
            logger.warn(() => `Get root manifest data from cache failed, check value in cache by key '${CLUSTER_ROOT_MANIFEST_DATA}'`, error);
        }
        return undefined;
    }

    async setRootManifestData(rootData) {
        logger.info(() => 'set manifest root data');
        try {
            await cacheDriver.setGuaranteed(CLUSTER_ROOT_MANIFEST_DATA, JSON.stringify(rootData));
        } catch (error) {
            logger.error(() => 'Update root data in cache failed', error);
        }
    }

    async getCommandState() {
        try {
            return await cacheDriver.get(CLUSTER_MASTER_COMMAND_STATE);
        } catch (error) {
            logger.warn(() => `Get command state from cache failed. Error ${error}`);
        }
        return undefined;
    }

    async setInfoProbeState(state, nodeId) {
        try {
            await cacheDriver.setGuaranteed(CLUSTER_MASTER_INFO_PROBE + nodeId, JSON.stringify(state));
        } catch (error) {
            logger.error(() => `Update info in cache failed. Error ${error}`);
        }
    }

    async getInfoProbeState(nodeId) {
        try {
            return JSON.parse(await cacheDriver.get(CLUSTER_MASTER_INFO_PROBE + nodeId));
        } catch (error) {
            logger.error(() => `Get info from cache failed. Error ${error}`);
        }
    }

    async getAllManifestState() {
        try {
            let infoArray = await cacheDriver.getValuesWhereKeyStartWith(CLUSTER_MANIFEST_META);
            return infoArray.map(el => JSON.parse(el));
        } catch (error) {
            logger.error(() => 'Get all manifest state. Error', error);
        }
    }

    async setCommand(command) {
        try {
            await cacheDriver.setGuaranteed(CLUSTER_MASTER_COMMAND, command);
            logger.debug(() => `Set command ${command} to cache`);
        } catch (error) {
            logger.warn(() => `Set command ${command} to cache failed. Error ${error}`);
        }
    }

    async getExpectTimeManifest(manifestAlias) {
        return Number(await cacheDriver.get(CLUSTER_MANIFEST_UPDATE_TIME_KEY + manifestAlias));
    }

    async setExpectTimeManifest(manifestAlias) {
        let currentTimestamp = Date.now();
        try {
            await cacheDriver.setGuaranteed(CLUSTER_MANIFEST_UPDATE_TIME_KEY + manifestAlias, currentTimestamp);
            logger.debug(() => `Set expected time for update to manifest ${manifestAlias} as ${currentTimestamp}`);
        } catch (error) {
            logger.warn(() => `Set expected time for update to manifest ${manifestAlias} with ${currentTimestamp} error`, error);
        }
    }

    async getActualManifestTimes() {
        return JSON.parse(await cacheDriver.get(CLUSTER_ALL_MANIFEST_ACTUAL_TIME_KEY));
    }

    async saveActualManifestTimes(actualState) {
        try {
            await cacheDriver.setGuaranteed(CLUSTER_ALL_MANIFEST_ACTUAL_TIME_KEY, JSON.stringify(actualState));
            logger.debug(() => 'actual manifest state saved success');
        } catch (error) {
            logger.warn(() => 'actual manifest state saved error', error);
        }
    }

    async status(nodeId) {
        try {
            let info = JSON.parse(await cacheDriver.get(CLUSTER_MASTER_INFO) || '{}');

            if (!info.updated || Date.now() - info.updated > CLUSTER_MASTER_TIMEOUT) {
                logger.info(() => `[myId ${nodeId}, masterId ${info.id}]: Old master died or not exist (last update timestamp ${info.updated}), now i'm a master`);
                info = {
                    id: nodeId,
                    counter: MASTER_SET_CHECK,
                    updated: Date.now()
                };
                await cacheDriver.setGuaranteed(CLUSTER_MASTER_INFO, JSON.stringify(info));
                await this.updateCommandState('Not ready');
                return {status: NodeStatus.WAIT, info: info};
            } else if (info.id === nodeId) {
                if (info.counter > 0 || !info.endLoadTime) {
                    const newInfo = {
                        id: nodeId,
                        counter: Math.max(info.counter - 1, 0),
                        updated: Date.now()
                    };
                    await cacheDriver.setGuaranteed(CLUSTER_MASTER_INFO, JSON.stringify(newInfo));
                    return {status: info.counter <= 1 ? NodeStatus.NO_MANIFEST : NodeStatus.WAIT, info: newInfo};
                } else {
                    info.updated = Date.now();
                    const refreshTimestampRaw = await cacheDriver.get(CLUSTER_COMMAND_REFRESH_TIMESTAMP);
                    const refreshTimestamp = refreshTimestampRaw && parseInt(refreshTimestampRaw);
                    if (!isNaN(refreshTimestamp) && info.endLoadTime < refreshTimestamp) {
                        logger.debug(() => `update info.endLoadTime with value ${refreshTimestamp} by value from cache (key ${CLUSTER_COMMAND_REFRESH_TIMESTAMP})`);
                        info.endLoadTime = refreshTimestamp;
                    } else if (refreshTimestampRaw) {
                        logger.debug(() => `${CLUSTER_COMMAND_REFRESH_TIMESTAMP} contains incorrect value [${refreshTimestampRaw}] (NaN or lower than info.endLoadTime [${info.endLoadTime}]), nothing to update`);
                    }
                    if (refreshTimestampRaw) {
                        await cacheDriver.del(CLUSTER_COMMAND_REFRESH_TIMESTAMP);
                    }
                    await cacheDriver.setGuaranteed(CLUSTER_MASTER_INFO, JSON.stringify(info));
                    return {status: NodeStatus.MASTER, endLoadTime: info.endLoadTime, info: info};
                }
            } else {
                return {status: info.endLoadTime ? NodeStatus.SLAVE : NodeStatus.WAIT, endLoadTime: info.endLoadTime, info: info};
            }
        } catch (error) {
            logger.warn(() => `Status communication to cache failed. Error ${error}`);
            if (error?.code === 'ECONNREFUSED') {
                return {status: NodeStatus.NOT_CONNECTED_TO_CACHE};
            }
        }
        return {status: NodeStatus.WAIT};
    }

    // TODO: т.к. манифест мы не иициализируем, то надо как-то переименовать
    async initializeManifest(endLoadTime) {
        try {
            const info = JSON.parse(await cacheDriver.get(CLUSTER_MASTER_INFO));
            info.endLoadTime = endLoadTime;
            await cacheDriver.setGuaranteed(CLUSTER_MASTER_INFO, JSON.stringify(info));
        } catch (error) {
            logger.warn(() => `Initialize manifest from cache failed. Error ${error}`);
        }
    }

    async getManifest(hash) {
        try {
            return JSON.parse(await cacheDriver.get(CLUSTER_MANIFEST + hash));
        } catch (error) {
            const traceId = uuidv4();
            logger.warn(() => `[${traceId}] Get manifest ${hash} from cache failed`, error);
            throw Error(`[${traceId}] Get manifest ${hash} from cache failed`, {cause: error});
        }
    }

    async clearCache() {
        logger.info(() => 'Clear cache start');
        let deletedKeyCount = 0;
        try {
            if (['postgres'].includes(datalakeCacheMode)) {
                deletedKeyCount = await cacheDriver.removeOldSeafCacheData();
            } else {
                logger.warn(() => `clearCache: cache mode not postgres (VUE_APP_DOCHUB_DATALAKE_CACHE = ${datalakeCacheMode}), nothing to clear`);
            }
        } catch (error) {
            logger.warn(() => `Clear cache cache failed. Error ${error}`);
        }
        logger.info(() => `cacheClear: delete finish, delete ${deletedKeyCount} keys`);
    }

    async close() {
        if (!cacheDriver) {
            logger.debug(() => 'cacheDriver not exist. nothing to close');
        }
        try {
            switch (datalakeCacheMode) {
                case 'postgres':
                    logger.debug(() => 'close postgres connection');
                    await cacheDriver.close();
                    cacheDriver = null;
                    break;
                default:
                    logger.debug(() => `cache mode not postgres (VUE_APP_DOCHUB_DATALAKE_CACHE = ${datalakeCacheMode}), nothing to close`);
            }
        } catch (e) {
            logger.error(() => 'error when try close cache', e);
            throw e;
        }
    }

    async init() {
      switch (datalakeCacheMode) {
        case 'redis':
            logger.error(() => redisUnsupportedMessage);
            throw Error(redisUnsupportedMessage);
        case 'postgres':
          logger.info(() => 'PostgresSQL is used as cluster cache ');
          cacheDriver = await postgres();
          break;
        default: {
            const errorMessage = `unknown datalake cache mode (VUE_APP_DOCHUB_DATALAKE_CACHE) [${datalakeCacheMode}], allow only [postgres]`;
            logger.error(() => errorMessage);
            throw Error(errorMessage);
        }
      }

      if (!cacheDriver) {
          const message = 'I can not create a cluster because connecting to cache DB is impossible';
          logger.error(() => message);
          throw new Error(message);
      }
    }

    async getClusterCache() {
      if (cacheDriver)
        return cacheDriver;

      await this.init();
      return cacheDriver;
    }
}
