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

import {ChangeLevelResult, SeafLogger, LogMessageFn} from '@global/logger/v2/logger.types';
import {logMessageToStringArray} from '@global/logger/v2/logMessageToStringArray.mjs';
import { changeLoggerImpl } from '@global/logger/v2/logger.mjs';
import { initSeafLoggerAPI } from '@front/logger/windowLoggerApi';

enum LogLevel {
  off =  0,
  error =  1,
  warn =  2,
  info =  3,
  debug =  4,
  trace =  5
}

// Тип для строкового представления уровней
type LogLevelName = keyof typeof LogLevel;

/**
 * Логгер для UI
 */
class FrontendLogger implements SeafLogger {
  private currentLevel: LogLevel = LogLevel.info;
  private readonly LOGGER_LEVEL_SESSION_STORAGE_KEY = 'seaf.logLevel';

  constructor() {
    const storedLevel = sessionStorage.getItem(this.LOGGER_LEVEL_SESSION_STORAGE_KEY);
    if (storedLevel) this.currentLevel = parseInt(storedLevel) as LogLevel;
    initSeafLoggerAPI(this);
  }

  trace(tag: string, msgFn: LogMessageFn, error?: unknown): void {
    this.log(LogLevel.trace, tag, msgFn, error);
  }

  error(tag: string, msgFn: LogMessageFn, error?: unknown): void {
    this.log(LogLevel.error, tag, msgFn, error);
  }

  info(tag: string, msgFn: LogMessageFn, error?: unknown): void {
    this.log(LogLevel.info, tag, msgFn, error);
  }

  debug(tag: string, msgFn: LogMessageFn, error?: unknown): void {
    this.log(LogLevel.debug, tag, msgFn, error);
  }

  warn(tag: string, msgFn: LogMessageFn, error?: unknown): void {
    this.log(LogLevel.warn, tag, msgFn, error);
  }

  getLevelName(): string {
    return LogLevel[this.currentLevel];
  }

  setLevel(level: string): ChangeLevelResult {
    const normalizedLevel = LogLevel[level.toLowerCase() as LogLevelName];
    if (!normalizedLevel && normalizedLevel !== LogLevel.off) { // т.к. off = 0 то его проверяем отдельно
      return {
        isSuccess: false,
        message: `Unknown log level: ${level}. Available levels: ${Object.keys(LogLevel)}`
      };
    }
    this.currentLevel = normalizedLevel;
    sessionStorage.setItem(this.LOGGER_LEVEL_SESSION_STORAGE_KEY, normalizedLevel.toString());
    // тут оставляем просто console.log, чтобы информация вывелась в любом случае
    // eslint-disable-next-line no-console
    console.log(`seaf.log: logger.ts: setLevel Log level changed to: ${LogLevel[normalizedLevel]}`);
    return {
      isSuccess: true,
      message: `log level changed to ${normalizedLevel}`
    };
  }

  private log(level: LogLevel, tag: string, msgFn: LogMessageFn, error?: unknown) {
    if (this.currentLevel >= level) {
      const levelTag = LogLevel[level];
      const timestamp = new Date().toISOString().substring(0, 23);
      const [header, ...details] = logMessageToStringArray(msgFn) || [];
      const message = `seaf.log: [${levelTag}] ${timestamp} ${tag} - ${JSON.stringify(header)}`;
      const shouldGroup = details.length > 0 || error;

      if (shouldGroup) {
        /* eslint-disable no-console */
        console.groupCollapsed(`%c${message}`, 'font-weight: bold');

        for (const msg of details) {
          if (!msg) {
            // ничего не делаем, пропускаем пустой элемент
          }
          console.log(`› ${msg}`);
        }

        if (error instanceof Error) {
          console.log('❌ Error:', error.message);
          console.log(error.stack);
        } else if (error) {
          console.log('❌ Unknown error:', error);
        }

        console.groupEnd();
      } else if (header) {
        console.log(message);
      }
      /* eslint-enable no-console */
    }
  }
}

export function initUiLogger() { changeLoggerImpl(new FrontendLogger()); }
