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
      Vladislav Markin <markinvy@yandex.ru>, Sber

  Contributors:
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2025
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
*/

import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import {CLUSTER_CACHE_PREFIX, CLUSTER_MANIFEST} from '@back/cluster/constants.mjs';
import {execWithRetry} from '@global/helpers/retry.mjs';
import {PG_PAUSE_BETWEEN_RETRY_MS_CONFIG, PG_RETRY_COUNT_CONFIG} from '@back/helpers/env.mjs';
import {getPgPool} from '@back/drivers/postgres/pool.mjs';

const LOG_TAG = 'postgres-driver';
const logger = getLoggerWithTag(LOG_TAG);

const TABLE_NAME = 'cache';

// не ошибка, целенаправленно делам включенным по дефолту
const useLockOnSet = process.env.VUE_APP_DOCHUB_POSTGRES_USE_LOCK_ON_SET?.toLowerCase() !== 'n';

export class PostgresCacheDriver {
  constructor(getPoolFn) {
    this.getPoolFn = getPoolFn;
    logger.info(() => `postgres start with config: retry count = ${PG_RETRY_COUNT_CONFIG} and pause between attempt = ${PG_PAUSE_BETWEEN_RETRY_MS_CONFIG}`);
    logger.info(() => `use lock on set value = ${useLockOnSet}`);

  }

  async init() {
    const createTableQuery = `
      CREATE UNLOGGED TABLE IF NOT EXISTS ${TABLE_NAME}
      (
        id varchar(128) PRIMARY KEY,
        value text
      );
    `;

    try {
      const client = await this.getPoolFn().connect();
      try {
        await client.query(createTableQuery);
      } catch (err) {
        logger.error(() => `Error on cache table creation: ${err.toString()}`);
      } finally {
        client.release();
      }
    } catch (err) {
      logger.error(() => `Error on connection establish: ${err.toString()}`);
    }
  }

  async set(key, value) {
    if (useLockOnSet) {
      await this.setIfPossible(key, value);
    } else {
      await this.setGuaranteed(key, value);
    }
  }

  /**
   * Установить значение в бд ориентируясь на блокировку строк в пг (row level lock) с ожиданием пока блокировка другим будет снята
   */
  async setGuaranteed(key, value) {
    const query = `
      INSERT INTO ${TABLE_NAME} (id, value)
      VALUES ($1, $2)
      ON CONFLICT (id)
      DO UPDATE SET value = EXCLUDED.value;
    `;
    await this.queryWithPool(query, [key, value]);
  }

  /**
   * Установить значение в бд с отдельной блокировкой, если блокировка занята, то insert/update не будет выполнен
   * Основное применение - для данных, которые несколько подов могут считать одновременно и получают идентичный результат
   * Один поток в одном поде берет блокировку и пишет, остальные не пишут и верят, что первый запишет
   */
  async setIfPossible(key, value) {
    await execWithRetry(PG_RETRY_COUNT_CONFIG, PG_PAUSE_BETWEEN_RETRY_MS_CONFIG, async() => {
      const client = await this.getPoolFn().connect();
      try {
        await client.query('BEGIN');
        const lockResult = await client.query('SELECT pg_try_advisory_xact_lock(hashtextextended($1, 0)) AS lock_acquired', [key]);
        const lockAcquired = lockResult.rows[0].lock_acquired;
        logger.trace(() => `lock status for row ${key} is ${lockAcquired}`);
        if (!lockAcquired) {
          logger.trace(() => `release lock for row ${key} by commit without change because lock is busy`);
          await client.query('COMMIT');
          return false;
        }
        const query = `
          INSERT INTO ${TABLE_NAME} (id, value)
          VALUES ($1, $2)
          ON CONFLICT (id)
          DO UPDATE SET value = EXCLUDED.value;
        `;
        await client.query(query, [key, value]);
        await client.query('COMMIT');
        logger.trace(() => `release lock for row ${key} by commit`);
      } catch (err) {
        await client.query('ROLLBACK');
        logger.trace(() => `release lock for row ${key} by rollback`);
        throw err;
      } finally {
        client.release();
      }
    });
  }

  async get(key) {
    const query = `SELECT value FROM ${TABLE_NAME} WHERE id = $1`;
    const result = await this.queryWithPool(query, [key]);
    return result.rows[0]?.value ?? null;
  }

  async getValuesWhereKeyStartWith(prefix) {
    const query = `SELECT value FROM ${TABLE_NAME} WHERE id like $1`;
    const result = await this.queryWithPool(query, [prefix + '%']);
    return result.rows?.map(el => el.value);
  }

  async getKeysLike(prefix) {
    const query = `SELECT id FROM ${TABLE_NAME} WHERE id like $1`;
    const result = await this.queryWithPool(query, [prefix + '%']);
    return result.rows?.map(el => el.id);
  }

  async removeOldSeafCacheData() {
    const idPrefix = CLUSTER_MANIFEST.replace(/_/g, '\\_') + '%';
    const query = `
        WITH manifest_hashes AS (
          SELECT substring(value FROM '"hash"\\s*:\\s*"([^"]+)"') AS hash
          FROM ${TABLE_NAME}
          WHERE id LIKE $1
        )
        DELETE
        FROM cache c
        WHERE c.id LIKE '${CLUSTER_CACHE_PREFIX}%'
            AND split_part(c.id, '.', 3) NOT IN (
              SELECT hash
              FROM manifest_hashes
              WHERE hash IS NOT NULL
            )`
    ;
    const result = await this.queryWithPool(query, [idPrefix]);
    return result.rowCount;
  }

  async del(key) {
    const query = `DELETE FROM ${TABLE_NAME} WHERE id = $1`;
    await this.queryWithPool(query, [key]);
  }
  
  async rename(from, to) {
    await execWithRetry(PG_RETRY_COUNT_CONFIG, PG_PAUSE_BETWEEN_RETRY_MS_CONFIG, async() => {
      const client = await this.getPoolFn().connect();
      try {
        await client.query('BEGIN');
        await client.query(`DELETE FROM ${TABLE_NAME} WHERE id = $1`, [to]);
        await client.query(`UPDATE ${TABLE_NAME} SET id = $2 WHERE id = $1`, [from, to]);
        await client.query('COMMIT');
      } catch (err) {
        await client.query('ROLLBACK');
        throw err;
      } finally {
        client.release();
      }
    });
  }

  async clear(key) {
    const query = `DELETE FROM ${TABLE_NAME} WHERE id LIKE $1`;
    await this.queryWithPool(query, [key + '%']);
  }

  async retainClear(key, notKey) {
    const query = `DELETE FROM ${TABLE_NAME} WHERE id LIKE $1 and not id LIKE $2`;
    await this.queryWithPool(query, [key + '%', notKey + '%']);
  }

  async close() {
    logger.info(() => 'close postgres pool');
    await this.getPoolFn().end();
  }

  async queryWithPool(query, params) {
    return await execWithRetry(PG_RETRY_COUNT_CONFIG, PG_PAUSE_BETWEEN_RETRY_MS_CONFIG, async() => {
      return await this.getPoolFn().query(query, params);
    });
  }
}
let driver = null;

export default async function() {
  if (driver) return driver;

  driver = new PostgresCacheDriver(getPgPool);
  await driver.init();

  logger.info(() => 'Postgres driver successfully initialized');

  return driver;
}
