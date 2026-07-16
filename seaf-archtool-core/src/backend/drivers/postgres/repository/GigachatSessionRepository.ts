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
import { SessionSerializable } from '@global/gigachat/session/type/SessionSerializable';
import { BasePostgresRepository, GetPoolFn } from '@back/drivers/postgres/repository/BasePostgresRepository';
import { PoolClient, QueryResult } from 'pg';
import { LockState } from '@back/drivers/postgres/dto/lockStates.mjs';

const logger = getLoggerWithTag('b/d/p/r/gigachatSessionRepository');
const TABLE_NAME = 'ai_chat_session_data';
class GigachatSessionRepositoryPg extends BasePostgresRepository {
    private readonly _sessionTtl: number;

    constructor(getPoolFn: GetPoolFn, sessionTtlMs) { // 90 seconds default for testing
        super(getPoolFn);
        this._sessionTtl = sessionTtlMs;
        this._initTable().then(() => {
            this._startCleanup();
        }).catch(error => {
            logger.error(() => 'Failed to initialize session table', error);
            throw error;
        });
    }

    private async _initTable(): Promise<void> {
        const createTableQuery = `
            CREATE UNLOGGED TABLE IF NOT EXISTS ${TABLE_NAME} (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                last_access BIGINT NOT NULL
            );
        `;
        try {
            await this._queryWithPoolSingle(createTableQuery);
        } catch (e) {
            if (e.message.startsWith('duplicate key value violates unique constraint')) {
                // много потоков в разных подах могут создать таблицу, появляется конфликт дубля
                // самое простое - игнорировать ошибку, если дубль, значит таблицу кто-то параллельно создал
                logger.info(() => `Session table initialized in another thread/node, this worker skip create: ${e.message}`);
                return;
            }
            throw e;
        }
        logger.info(() => 'Session table initialized successfully');
    }

    public async save(session: SessionSerializable): Promise<void> {
        logger.debug(() => `Saving session ${session.id}`);

        const data = JSON.stringify(session);

        // Для колонок используем отдельные поля
        const { id, lastAccess } = session;

        const query = `
            INSERT INTO ${TABLE_NAME} (id, data, last_access)
            VALUES ($1, $2, $3)
            ON CONFLICT (id) 
            DO UPDATE SET
                data = EXCLUDED.data,
                last_access = EXCLUDED.last_access
        `;

        try {
            await this._queryWithPoolSingle(query, [id, data, lastAccess]);
            logger.trace(() => `Session ${session.id} saved successfully`);
        } catch (error) {
            logger.error(() => `Failed to save session ${session.id}:`, error);
            throw error;
        }
    }

    public async updateLastAccess(sessionId: string, lastAccess: number): Promise<boolean> {
        logger.debug(() => `updateLastAccess session ${sessionId}`);

        const query = `UPDATE ${TABLE_NAME} SET last_access = $1 WHERE id = $2 returning id`;

        try {
            const result = await this._queryWithPoolSingle(query, [lastAccess, sessionId]);
            if (result.rowCount > 0) {
                logger.debug(() => `Session ${sessionId} update last_access successfully, result row count ${result.rowCount}`);
                return true;
            } else {
                logger.debug(() => `Session ${sessionId} not exist, not update update last_access`);
                return false;
            }
        } catch (error) {
            logger.error(() => `Failed to update last_access ${sessionId}:`, error);
            throw error;
        }
    }

    public async getById(id: string): Promise<SessionSerializable | null> {
        logger.debug(() => `Fetching session ${id}`);

        const query = `SELECT data FROM ${TABLE_NAME} WHERE id = $1`;

        try {
            const result = await this._queryWithPoolSingle(query, [id]) as QueryResult;

            if (result.rows.length === 0) {
                logger.trace(() => `Session ${id} not found`);
                return null;
            }

            // Парсим полный объект из data - он уже содержит id и lastAccess внутри
            const session = JSON.parse(result.rows[0].data) as SessionSerializable;
            logger.trace(() => `Session ${id} fetched successfully`);
            return session;

        } catch (error) {
            logger.error(() => `Failed to fetch session ${id}:`, error);
            throw error;
        }
    }

    public async deleteById(id: string): Promise<boolean> {
        logger.debug(() => `Deleting session ${id}`);

        const query = `DELETE FROM ${TABLE_NAME} WHERE id = $1 RETURNING id`;

        try {
            const result = await this._queryWithPoolSingle(query, [id]) as QueryResult;

            if (result.rowCount === 0) {
                logger.trace(() => `Session ${id} not found for deletion`);
                return false;
            }

            logger.trace(() => `Session ${id} deleted successfully`);
            return true;

        } catch (error) {
            logger.error(() => `Failed to delete session ${id}`, error);
            throw error;
        }
    }

    private runCleanup = async(): Promise<void> => {
        try {
            const cutoffTime = Date.now() - this._sessionTtl;
            const lockKey = 'session_cleanup';

            const result = await this._executeWithAdvisoryLock(lockKey, async(client: PoolClient) => {
                const query = `DELETE FROM ${TABLE_NAME} WHERE last_access < $1 RETURNING id`;
                return await client.query<{ id: string }>(query, [cutoffTime]);
            });

            if (result === LockState.NOT_ACQUIRED) {
                logger.trace(() => 'Cleanup skipped - lock held by another instance');
            } else if (result && result.rowCount > 0) {
                logger.info(() => `Cleaned up ${result.rowCount} expired sessions`);
                logger.debug(() => `Removed session IDs: ${result.rows.map(r => r.id).join(', ')}`);
            } else {
                logger.trace(() => 'No expired sessions to clean up');
            }

        } catch (error) {
            logger.error(() => 'Error during session cleanup:', error);
        } finally {
            setTimeout(this.runCleanup, this._sessionTtl);
        }
    };

    private _startCleanup(): void {
        logger.info(() => `Starting session cleanup with TTL ${this._sessionTtl}ms`);
        setTimeout(this.runCleanup, this._sessionTtl);
    }
}

export default GigachatSessionRepositoryPg;
