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

import { getLoggerWithTag } from '@global/logger/v2/logger.mjs';
import { execWithRetry } from '@global/helpers/retry.mjs';
import { Pool, PoolClient, QueryResult } from 'pg';
import {PG_PAUSE_BETWEEN_RETRY_MS_CONFIG, PG_RETRY_COUNT_CONFIG} from '@back/helpers/env.mjs';
import { LockState } from '@back/drivers/postgres/dto/lockStates.mjs';

const logger = getLoggerWithTag('b/d/p/r/basePostgresRepository');

export type GetPoolFn = () => Pool;

// Базовый класс с общими методами для работы с PostgreSQL
export abstract class BasePostgresRepository {
    protected _getPoolFn: GetPoolFn;

    protected constructor(getPoolFn: GetPoolFn) {
        this._getPoolFn = getPoolFn;
    }

    /**
     * Выполнить операцию (запросы) с ретраем.
     * Количество ретраев и пауза между ними задается в окружении, параметрами:
     * VUE_APP_DOCHUB_POSTGRES_PAUSE_BETWEEN_RETRY_MS
     * VUE_APP_DOCHUB_POSTGRES_RETRY_COUNT
     * @param operation - операция которую надо выполнить
     * @protected
     */
    protected async _execWithRetry<T>(operation: () => Promise<T>): Promise<T> {
        return await execWithRetry(PG_RETRY_COUNT_CONFIG, PG_PAUSE_BETWEEN_RETRY_MS_CONFIG, operation);
    }

    /**
     * Выполнить операцию (запросы) на одном коннекте
     * @param operation - операция которую надо выполнить
     * @protected
     */
    protected async _queryWithPool<T>(operation: (client: PoolClient) => Promise<T>): Promise<T> {
        const client = await this._getPoolFn().connect();
        try {
            return await operation(client);
        }  finally {
            client.release();
        }
    }

    /**
     * Выполнить один запрос на новом коннекте, просто передать query и params в новое соединение
     * @param query - запрос
     * @param params - параметры запроса
     * @protected
     */
    protected async _queryWithPoolSingle(query: string, params?: any[]): Promise<QueryResult> {
        return await this._getPoolFn().query(query, params);
    }

    /**
     * Взять блокировку в пг через pg_try_advisory_xact_lock
     * Функцию есть смысл вызывать если есть открытая транзакция, т.к. лок берется в пределах транзакции
     * Например, если есть свой процесс и в середине своей транзакции нужен лок
     * @param key - ключ для которого будет взята блокировка
     * @param client - соединение в котором выполняются запросы
     * @return - LockState блокировки получилось взять или нет
     * @protected
     */
    protected async _getLock(key: string, client: PoolClient): Promise<LockState> {
        const lockResult = await client.query<{ lock_acquired: boolean }>(
            'SELECT pg_try_advisory_xact_lock(hashtextextended($1, 0)) AS lock_acquired',
            [key]
        );

        const lockAcquired = lockResult.rows[0].lock_acquired;
        logger.trace(() => `Lock status for key ${key} is ${lockAcquired}`);

        if (!lockAcquired) {
            logger.trace(() => 'Lock is busy, another instance will handle operation');
            return LockState.NOT_ACQUIRED;
        }
        return LockState.ACQUIRED;
    }

    /**
     * Взять блокировку в пг через метод _getLock и выполнить операцию (запросы) в транзакции
     * Используется, если всю операцию надо выполнить с блокировкой
     * Если блокировку взять не получилось вернется LockState.NOT_ACQUIRED
     * @param key - ключ для которого будет взята блокировка
     * @param operation - соединение в котором выполняются запросы
     * @return - результат выполнения операции или LockState.NOT_ACQUIRED
     * @protected
     */
    protected async _executeWithAdvisoryLock<T>(key: string, operation: (client: PoolClient) => Promise<T>): Promise<T | LockState> {
        return await this._execInTransaction(async(client) => {
            const lockAcquired = await this._getLock(key, client);
            if (lockAcquired) {
                return await operation(client);
            }
            return LockState.NOT_ACQUIRED;
        });
    }

    /**
     * Выполнить операцию (запросы) на одном коннекте в пределах одной транзакции
     * @param operation - операция которую надо выполнить
     * @protected
     */
    protected async _execInTransaction<T>(operation: (client: PoolClient) => Promise<T>): Promise<T> {
        return await this._queryWithPool(async(client) => {
            try {
                await client.query('BEGIN');
                const result = await operation(client);
                await client.query('COMMIT');
                return result;
            } catch (error) {
                await client.query('ROLLBACK');
                logger.error(() => `Error in transaction: ${error instanceof Error ? error.message : String(error)}`);
                throw error;
            }
        });
    }
}
