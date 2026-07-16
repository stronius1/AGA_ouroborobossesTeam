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
*/


import {SeafLogger} from '@global/logger/v2/logger.types';

/**
 * API для управления логгером через функцию window
 */
interface SeafLoggerAPI {
    setLogLevel(level: string): void;
    getLogLevel(): string;
}

/**
 * Объявляем расширение Window управления логгером
 */
declare global {
    interface Window {
        seafLoggerApi?: SeafLoggerAPI;
    }
}

/**
 * Инициализация API
 * @param logger - логгер, которым API будет управлять
 */
export function initSeafLoggerAPI(logger: SeafLogger): SeafLoggerAPI {
    const api: SeafLoggerAPI = {
        setLogLevel: (level) => logger.setLevel(level),
        getLogLevel: () => logger.getLevelName()
    };

    if (!window.seafLoggerApi) {
        window.seafLoggerApi = api;
    } else {
        // Добавляем к существующиму API
        window.seafLoggerApi = { ...window.seafLoggerApi, ...api };
    }

    return window.seafLoggerApi;
}
