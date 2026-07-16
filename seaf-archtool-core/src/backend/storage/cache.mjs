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
      R.Piontik <r.piontik@mail.ru> - 2023
      R.Piontik <r.piontik@mail.ru> - 2024
      Vladislav Nefedov <clay.zenx@gmail.com>, Sber - 2023
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2024
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2025
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2025
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
      Vladislav Markin, Sber - 2026
*/

import prototype from '../../global/manifest/services/cache.mjs';
import request from '../helpers/request.mjs';
import { fileURLToPath } from 'url';
import path from 'path';
import fs from 'fs';
import md5 from 'md5';
import createPostgresClient from '../drivers/postgres.mjs';
import { performance } from 'node:perf_hooks';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import {CLUSTER_MANIFEST} from '@back/cluster/constants.mjs';
import {MAX_CACHE_LINE_LENGTH} from '@back/helpers/env.mjs';
import {Mutex} from 'async-mutex';
import { envelopeDocument } from '@global/helpers/api/envelope.js';

const LOG_TAG = 'manifest-cache';
const logger = getLoggerWithTag(LOG_TAG);

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const cacheMode = (process.env.VUE_APP_DOCHUB_DATALAKE_CACHE || 'none').toLocaleLowerCase();

//редис удален в задаче ERA-1986 03.2026 спустя какое-то время эту проверку можно будет убрать как и остальные упоминания редиса
if (cacheMode === 'redis') {
    throw Error(`redis cache now not supported, check env VUE_APP_DOCHUB_DATALAKE_CACHE, current value ${cacheMode}`);
}

const pgClient = cacheMode === 'postgres' ? await createPostgresClient() : null;

export function loadFromAssets(filename) {
    const source = path.resolve(__dirname, '../../assets/' + filename);

    logger.info(() => `Import base metamodel from  [${source}].`);
    return fs.readFileSync(source, { encoding: 'utf8', flag: 'r' });
}

function getDataMd5Key(prefix, key) {
    return `SEAF.cache.${prefix || 'unknown'}.${md5(key)}`;
}

// Кэш в памяти
let memoryCache = {};
let cacheLocks = new Map();

const errorType = {
    system: 'Внутрисистемная ошибка',
    syntax: 'Синтаксическая ошибка',
    net: 'Сетевая ошибка'
};

async function pullWithDriver(cache, driver, resolve, md5Key, key) {
    if(!cacheLocks.has(md5Key)) {
        cacheLocks.set(md5Key, new Mutex());
    }
    return await cacheLocks.get(md5Key)
        .runExclusive(async() => {
            let result = memoryCache[md5Key]?.deref();
            if (!result) {
                result = await driver.get(md5Key);
                if (result) {
                    logger.trace(() => `pullWithDriver: get ${key} (${md5Key}) len ${result.length}`);
                    result = cache.cacheToObject(result)?.value;
                } else {
                    if (resolve) {
                        const startTime = performance.now();
                        result = await resolve();
                        logger.trace(() => `${key} \n Time: ${performance.now() - startTime}ms`);
                        const cacheLine = cache.objectToCache({value: result});
                        const cacheLineLength = cacheLine?.length;
                        logger.trace(() => `pullWithDriver: resolve ${key} (${md5Key}) ` + (cacheLine ? `len ${cacheLineLength}` : 'nothing'));
                        if (cacheLineLength > MAX_CACHE_LINE_LENGTH) {
                            throw Error(`Save value to cache by key ${key} over limit (length: ${cacheLineLength}, limit: ${MAX_CACHE_LINE_LENGTH}), md5key = [${md5Key}]`);
                        }
                        await driver.set(md5Key, cacheLine);
                    }
                }
                // eslint-disable-next-line no-undef
                memoryCache[md5Key] = result && typeof result === 'object' ? new WeakRef(result) : null;
            } else {
                logger.trace(() => `pullWithDriver: key ${key} (${md5Key}) found in memory cache`);
            }
            return result;
        });
}

async function putWithDriver(cache, driver, resolve, md5Key, key) {
    if(!cacheLocks.has(md5Key)) {
        cacheLocks.set(md5Key, new Mutex());
    }
    return await cacheLocks.get(md5Key)
        .runExclusive(async() => {
            const value = await resolve();
            const cacheLine = cache.objectToCache({ value });
            const cacheLineLength = cacheLine?.length;
            if (cacheLineLength > MAX_CACHE_LINE_LENGTH) {
                throw Error(`Save value to cache by key ${key} over limit (length: ${cacheLineLength}, limit: ${MAX_CACHE_LINE_LENGTH}), md5key = [${md5Key}]`);
            }
            await driver.set(md5Key, cacheLine);
            // eslint-disable-next-line no-undef
            memoryCache[md5Key] = value && typeof value === 'object' ? new WeakRef(value) : null;
            return value;
        });
}

export default Object.assign(prototype, {

    isClusterCache: false,
    // Содержит ошибки, которые возникли за сессию
    errors: {},
    // Очищает регистр ошибок
    errorClear() {
        this.errors = {};
    },

    async getManifest(key) {
        try {
            return JSON.parse(await this.get(CLUSTER_MANIFEST + key));
        } catch (error) {
            logger.warn(() => `Get manifest from cache failed. Error ${error}`);
        }
        return undefined;
    },

    async get(key) {
      switch (cacheMode) {
        case 'postgres':
            return await pgClient.get(key);
        default: {
          return undefined;
        }
      }
    },

    async set(key, value) {
      switch (cacheMode) {
        case 'postgres':
            return await pgClient.set(key, value);
        default: {
          return undefined;
        }
      }
    },
    // Очистка кэша
    //  prefix - Префикс, который будет использован перед ключом
    async clearCache(prefix) {
      switch (cacheMode) {
        case 'none': return;
        case 'memory': await this.clearMemoryCache(); break;
        case 'postgres':
          await pgClient.clear(`SEAF.cache.${prefix || ''}`);
          await this.clearMemoryCache();
          break;
        default: {
          const cacheDir = path.resolve(__dirname, '../../../', cacheMode);
          fs.readdir(cacheDir, (err, files) => {
            if (err) throw err;
            for (const file of files) {
              fs.unlink(`${cacheDir}/${file}`, err => logger.error(() => 'clearCache fs error',  err));
            }
          });
        }
      }
    },
    async clearMemoryCache() {
        memoryCache = {};
    },
    // Регистрирует ошибку
    // type         - Секция ошибки (system/syntax/net)
    // uid          - Уникальный идентификатор ошибки.
    // title        - Определяет представление ошибки в дереве.
    // location     - URL с расположением объекта, где выявлена ошибка.
    // correction   - Краткое пояснение, как исправить ошибку.
    // description  - Описание причины ошибки.
    registerError(type, uid, title, location, correction, description) {
        !this.errors[type] && (this.errors[type] = {
            id: `$error.${type}`,
            title: errorType[type] || 'Неизвестная ошибка',
            items: []
        });
        logger.error(() => `${title}: ${description} [${location}]`);
        this.errors[type].items.push({
            uid, title, location, correction, description
        });
    },
    objectToCache(obj) {
        const res = typeof obj === 'string' ? { SEAF_cache_string: obj } : obj;
        return JSON.stringify(res);
    },
    cacheToObject(cacheString) {
        const cacheObj = JSON.parse(cacheString);
        return cacheObj.SEAF_cache_string ? cacheObj.SEAF_cache_string : cacheObj;
    },
    // Получает данные из кэша
    //  prefix - Префикс, который будет использован перед ключом
    //  key - ключ
    //  resolve - если в кэше данные не будут найдены, будет вызвана функция для генерации данных
    //  res - response объект express. Если указано, то ответ сразу отправляется клиенту
    //  envelope - Если true, ответ упаковывается в транспортный формат
    async pullFromDataCache(prefix, key, resolve, res, envelope) {
        let fileName = null;
        const md5Key = getDataMd5Key(prefix, key);
        try {
            let result = null;

            switch (cacheMode) {
              case 'none':
                if(resolve) {
                  result = await resolve();
                } else {
                  result = undefined;
                }
                break;
              case 'memory':
                result = memoryCache[md5Key]
                  || (resolve && (memoryCache[md5Key] = await resolve()));
                break;
              case 'postgres':
                result = await pullWithDriver(this, pgClient, resolve, md5Key, key);
                break;
              default: {
                fileName = path.resolve(__dirname, '../../../', cacheMode, `${md5Key}.cache`);
                if (!fs.existsSync(fileName)) {
                  result = this.objectToCache(await resolve() || null);
                  fs.writeFileSync(fileName, result, { encoding: 'utf8' });
                }
                logger.debug(() => `__dirname: '${__dirname}', fileName: '${fileName}'`);
                result = this.cacheToObject(fs.readFileSync(fileName, { encoding: 'utf8' }));
              }
            }

            if (res) {
              if (envelope) {
                result = envelopeDocument(result);
              }
              res.status(200).json(result);
            }

            return res ? true : result;
        } catch (e) {
            const message = typeof e === 'string' ? e : e.message;
            this.registerError('system', md5Key, `Cache error while pulling ${key} (${md5Key})`, fileName || cacheMode, 'See error log at backed server', message);
            if (res) {
                res.status(500);
                res.json({
                    message,
                    error: e
                });
            }
            return Promise.reject(e);
        }
    },

    async updateInDataCache(prefix, key, resolve) {
      let fileName = null;
      let result;
      const md5Key = getDataMd5Key(prefix, key);

      try {
        switch (cacheMode) {
          case 'none':
            result = resolve && await resolve() || undefined;
            break;
          case 'memory':
            memoryCache[md5Key] = resolve ? await resolve() : null;
            result = memoryCache[md5Key];
            break;
          case 'postgres':
            result = await putWithDriver(this, pgClient, resolve, md5Key, key);
            break;
          default: {
            fileName = path.resolve(__dirname, '../../../', cacheMode, `${md5Key}.cache`);
            result = this.objectToCache( await resolve() || null);
            fs.writeFileSync(fileName, result, { encoding: 'utf8' });
          }
        }

        if (fileName) {
            result = this.cacheToObject(fs.readFileSync(fileName, { encoding: 'utf8' }));
        }
      } catch (e) {
        const message = typeof e === 'string' ? e : e.message;
        this.registerError('system', md5(key), 'Cache error while updating', fileName || cacheMode, 'See error log at backed server', message);
        return Promise.reject(e);
      }

      return result;
    },

    async moveInDataCache(sourcePrefix, sourceKey, targetPrefix, targetKey) {
      const source = getDataMd5Key(sourcePrefix, sourceKey);
      const target = getDataMd5Key(targetPrefix, targetKey);
      try {
        switch (cacheMode) {
          case 'none':
            return;
          case 'memory':
            memoryCache[target] = memoryCache[source];
            memoryCache[source] = null;
            break;
          case 'postgres':
            // TODO: do it properly
            await pgClient.rename(source, target);
            break;
          default: {
            const sourceFileName = path.resolve(__dirname, '../../../', cacheMode, `${source}.cache`);
            const targetFileName = path.resolve(__dirname, '../../../', cacheMode, `${target}.cache`);
            if (fs.existsSync(sourceFileName)) {
              fs.renameSync(sourceFileName, targetFileName);
            }
          }
        }
      } catch (e) {
        const message = typeof e === 'string' ? e : e.message;
        this.registerError('system', source, 'Cache error while moving', cacheMode, 'See error log at backed server', message);
        return Promise.reject(e);
      }
    },

    // Выполняет запрос к данным
    async request(url) {
        let result = null;
        try {
            result = await request(url);
        } catch(e) {
            this.registerError('net', md5(url), 'Request error', url, 'See details in error log of backed server', e.message);
            throw e;
        }
        logger.debug(() => `Source [${url}] is imported.`);
        return result;
    }
});

