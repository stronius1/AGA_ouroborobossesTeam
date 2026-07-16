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
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
	    R.Piontik <r.piontik@mail.ru> - 2023
      Temnyakov Nikolay <temnjakovn@gmail.com>, Sber - 2024
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2025
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
*/

// Подключаем переменные среды
import path from 'path';
import os from 'os';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';
import process from 'node:process';
import {parsePositiveOrZero, toNumerOrDefault} from '@global/helpers/numberUtils.mjs';

const ENV_FILES = process.env.VUE_APP_ENV_FILES?.split(',')?.map((p) => path.resolve(p));

dotenv.config({
    ...(ENV_FILES && {
        path: ENV_FILES
    })
});

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const SMARTANTS_PATH = process.env.VUE_APP_DOCHUB_SMART_ANTS_PATH ?? 'smartants/';
const SMARTANTS_BASE = new URL(SMARTANTS_PATH, process.env.VUE_APP_DOCHUB_SMART_ANTS_ADDRESS ?? 'http://127.0.0.1');
SMARTANTS_BASE.port = process.env.VUE_APP_DOCHUB_SMART_ANTS_PORT ?? 3040;

const manifestOnBitbucket = process.env.VUE_APP_DOCHUB_ROOT_MANIFEST?.startsWith('bitbucket:') ?? false;
const MAX_REQUEST_ATTEMPTS = process.env.VUE_APP_DOCHUB_MAX_REQUEST_REPEAT_ATTEMPTS ?? manifestOnBitbucket ? 3 : 0;
const MAX_HTTP_SOCKETS = process.env.VUE_APP_DOCHUB_MAX_HTTP_SOCKETS ?? manifestOnBitbucket ? 100 : undefined;

const eTagUsage = (() => {
  const ETagUsageValues = ['ON', 'OFF', 'STATIC', 'API']; // Value with index 0 is default
  const value = (process.env.VUE_APP_DOCHUB_ETAG || ETagUsageValues[0]).toUpperCase();
  if (ETagUsageValues.includes(value)) {
    return value;
  } else {
    return ETagUsageValues[0];
  }
})();

export const hasStaticEtag = ['ON', 'STATIC'].includes(eTagUsage);
export const hasAPIEtag = ['ON', 'API'].includes(eTagUsage);
export const ROLES_MODE_V2_VALUE = process.env.VUE_APP_DOCHUB_ROLES_MODEL_V2;
export const ROLES_MODE_V2_ENABLED = ROLES_MODE_V2_VALUE?.toLowerCase() === 'y';
export const MAX_CACHE_LINE_LENGTH = toNumerOrDefault(process.env.VUE_APP_DOCHUB_MAX_CACHE_LINE_LENGTH, Number.MAX_SAFE_INTEGER);

export const PG_RETRY_COUNT_CONFIG = parsePositiveOrZero(process.env.VUE_APP_DOCHUB_POSTGRES_RETRY_COUNT);
export const PG_PAUSE_BETWEEN_RETRY_MS_CONFIG = parsePositiveOrZero(process.env.VUE_APP_DOCHUB_POSTGRES_PAUSE_BETWEEN_RETRY_MS);

export const GIGACHAT_SESSION_TTL_MS = toNumerOrDefault(process.env.VUE_APP_DOCHUB_GIGACHAT_SESSION_TTL_MS, 900000);
export const GIGACHAT_MAX_MESSAGE_COUNT_IN_HISTORY = toNumerOrDefault(process.env.VUE_APP_DOCHUB_GIGACHAT_MAX_MESSAGE_COUNT_IN_HISTORY, Number.MAX_SAFE_INTEGER);
export const GIGACHAT_MAX_SUM_SYMBOL_OF_ALL_MESSAGES = toNumerOrDefault(process.env.VUE_APP_DOCHUB_GIGACHAT_MAX_SUM_SYMBOL_OF_ALL_MESSAGES, Number.MAX_SAFE_INTEGER);


global.$paths = {
    public: path.resolve(__dirname, '../../../public/'),
    dist: path.resolve(__dirname, '../../../dist/'),
    file_storage: (
        process.env.VUE_APP_DOCHUB_BACKEND_FILE_STORAGE 
        ? path.resolve(process.env.VUE_APP_DOCHUB_BACKEND_FILE_STORAGE) 
        : path.resolve(__dirname, '../../../public/')
    )
};

global.$listeners = {
    onFoundLoadingError: process.env.VUE_APP_DOCHUB_BACKEND_EVENT_LOADING_ERRORS_FOUND
};

global.$logger = {
    level: process.env.VUE_APP_DOCHUB_LOGGER_LEVEL ?? 'info',
    logfile: process.env.VUE_APP_DOCHUB_LOGGER_LOGFILE,
    jsonataLogfile: process.env.VUE_APP_DOCHUB_JSONATA_LOGFILE,
    profileEnable: process.env.VUE_APP_DOCHUB_PERF_LOGGER_ENABLE === 'on',
    profileLogToConsole: process.env.VUE_APP_DOCHUB_PERF_TO_CONSOLE === 'on',
    perfLogfile: process.env.VUE_APP_DOCHUB_PERF_LOGFILE
};

global.$roles = {
    MODE: process.env.VUE_APP_DOCHUB_ROLES_MODEL,
    URI: process.env.VUE_APP_DOCHUB_ROLES
};

global.$smartants = {
    source: (
        process.env.VUE_APP_DOCHUB_SMART_ANTS_SOURCE
        ? path.resolve(__dirname, `../../..${process.env.VUE_APP_DOCHUB_SMART_ANTS_SOURCE}`)
        : path.resolve(__dirname, '../../assets/libs/smartants.cjs')
    ),
    mode: process.env.VUE_APP_DOCHUB_SMART_ANTS_MODE ?? 'frontend',
    pathUrl: SMARTANTS_PATH,
    baseUrl: SMARTANTS_BASE,
    maxWorkers: process.env.VUE_APP_DOCHUB_SMART_ANTS_MAX_THREADS ?? Math.max(os.cpus().length - 2, 1),
    workerTimeout: process.env.VUE_APP_DOCHUB_SMART_ANTS_WORKER_TIMEOUT ?? 50000
};

global.$httpRepeater = {
    maxRetries: MAX_REQUEST_ATTEMPTS,
    maxSockets: MAX_HTTP_SOCKETS
};

export function findAnyY(array) {
    if (!array || !Array.isArray(array) || array.length === 0) {
        return 'N';
    }
    for (let i = 0; i < array.length; i++) {
        const item = array[i];
        if (typeof item === 'string' && item.toUpperCase() === 'Y') {
            return item; // возвращаем в оригинальном регистре
        }
    }
}

export default dotenv;
