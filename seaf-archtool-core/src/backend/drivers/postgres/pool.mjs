/*
  Copyright (C) 2026 Sber

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
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber
*/

import {Pool} from 'pg';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

const logger = getLoggerWithTag('b/d/p/pool');
let pool = null;

const enableConnectionStat = process.env.VUE_APP_DOCHUB_LOG_POSTGRES_CONNECTION?.toLowerCase() === 'y';

let poolConfig = {
    'connectionString': process.env.VUE_APP_DOCHUB_POSTGRES_URL,
    max: process.env.VUE_APP_POSTGRES_POOL_SIZE || 50,
    idleTimeoutMillis: (process.env.VUE_APP_POSTGRES_IDLE_TIMEOUT_SECONDS || 300) * 1000,
    connectionTimeoutMillis: (process.env.VUE_APP_POSTGRES_CONNECTION_TIMEOUT_SECONDS || 5) * 1000,
    acquireTimeoutMillis: (process.env.VUE_APP_POSTGRES_ACQUIRE_TIMEOUT_SECONDS || 180) * 1000,
    allowExitOnIdle: false // предотвращает закрытие при простое
};

export function getPgPool() {
    if (!pool || pool.ending) {
        if (pool?.ending === true) {
            logger.info(() => 'postgres pool was closed by somebody, open new');
        }
        pool = new Pool(poolConfig);
        if (enableConnectionStat) {
            logger.debug(() => 'postgres pool metrics enabled');
            setupEventListeners(pool);
        } else {
            logger.debug(() => 'postgres pool metrics disabled. If need, may enabled by VUE_APP_DOCHUB_LOG_POSTGRES_CONNECTION env with "Y" value');
        }
        pool.on('error', (err) => {
            logger.error(() => 'error in pool', err);
        });
    }
    return pool;
}


const stats = {
    connectionsCreated: 0,      // connect
    connectionsDestroyed: 0,    // remove
    connectionsAcquired: 0,     // acquire
    connectionsReleased: 0,     // release
    errorsCount: 0,             // error
    openedConnection: 0,        // открытые соединения
    connectionInUse: 0          // соединения в использовании
};

function getInternalMetrics(pool) {
    return {
        total: pool.totalCount,
        idle: pool.idleCount,
        waiting: pool.waitingCount
    };
}

function setupEventListeners(pool) {
    // Создано новое физическое соединение
    pool.on('connect', () => {
        stats.connectionsCreated++;
        stats.openedConnection++;

        logger.debug(() => [
            'pg pool create new connect',
            { title: 'event', obj: 'connect' },
            { title: 'stats', obj: { ...stats } },
            { title: 'poolInternal', obj: getInternalMetrics(pool) }
        ]);
    });

    // Клиент взят из пула
    pool.on('acquire', () => {
        stats.connectionsAcquired++;
        stats.connectionInUse++;
        logger.debug(() => [
            'pg pool use connect from pool',
            { title: 'event', obj: 'acquire' },
            { title: 'stats', obj: { ...stats } },
            { title: 'poolInternal', obj: getInternalMetrics(pool) }
        ]);
    });

    // Клиент возвращен в пул
    pool.on('release', (err) => {
        stats.connectionsReleased++;
        stats.connectionInUse = Math.max(0, stats.connectionInUse - 1);

        if (err) {
            stats.errorsCount++;
            logger.debug(() => [
                'pg pool error when release connect',
                { title: 'event', obj: 'release_error' },
                { title: 'error', obj: err.message },
                { title: 'stats', obj: { ...stats } },
                { title: 'poolInternal', obj: getInternalMetrics(pool) }
            ]);
        } else {
            logger.debug(() => [
                'pg pool success release connect',
                { title: 'event', obj: 'release' },
                { title: 'stats', obj: { ...stats } },
                { title: 'poolInternal', obj: getInternalMetrics(pool) }
            ]);
        }
    });

    // Соединение удалено из пула
    pool.on('remove', () => {
        stats.connectionsDestroyed++;
        stats.openedConnection = Math.max(0, stats.openedConnection - 1);

        // Если соединение было активным при удалении, уменьшаем и активные
        // Но берем Math.max чтобы не уйти в отрицательные, если уже учли в release
        if (stats.connectionInUse > 0) {
            stats.connectionInUse = Math.max(0, stats.connectionInUse - 1);
        }

        logger.debug(() => [
            'pg pool close connect',
            { title: 'event', obj: 'remove' },
            { title: 'stats', obj: { ...stats } },
            { title: 'poolInternal', obj: getInternalMetrics(pool) }
        ]);
    });

    // Ошибка на клиенте
    pool.on('error', (err) => {
        stats.errorsCount++;
        logger.debug(() => [
            'pg pool error on client when try to connect',
            { title: 'event', obj: 'connection_error' },
            { title: 'error', obj: err.message },
            { title: 'stats', obj: { ...stats } },
            { title: 'poolInternal', obj: getInternalMetrics(pool) }
        ]);
    });
}
