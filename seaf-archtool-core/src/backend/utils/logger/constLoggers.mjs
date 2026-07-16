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

import {newLogger} from '@back/utils/logger/logger-factory.mjs';

/**
 * Главный логгер для бекенда
 */
export const mainLogger = newLogger({
    logFileName: global.$logger.logfile,
    defaultLevel: global.$logger.level
});

/**
 * Отдельный логгер для записи производительности jsonata
 */
export const jsonataLogger = newLogger({
    logFileName: global.$logger.jsonataLogfile,
    defaultLevel: 'debug',
    consoleLevel: 'error'
});

/**
 * Отдельный логгер для записи производительности системы
 */
export const profileLogger = newLogger({
    logFileName: global.$logger.perfLogfile,
    defaultLevel: global.$logger.level,
    enableConsoleLog:  global.$logger.profileLogToConsole
});
