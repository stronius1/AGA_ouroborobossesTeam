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
import {logMessageToStringArray} from '@global/logger/v2/logMessageToStringArray';
import { changeLoggerImpl } from '@global/logger/v2/logger';

enum LogLevel {
    off =  0,
    error =  1,
    warn =  2,
    info =  3,
    debug =  4,
    trace =  5
}

/**
 * Логгер для UI
 */
class PluginLogger implements SeafLogger {
    private currentLevel: LogLevel = LogLevel.debug;


    error(tag: string, msgFn: LogMessageFn, error?: unknown): void {
        this.log(LogLevel.error, tag, msgFn, error);
    }

    warn(tag: string, msgFn: LogMessageFn, error?: unknown): void {
        this.log(LogLevel.warn, tag, msgFn, error);
    }

    info(tag: string, msgFn: LogMessageFn, error?: unknown): void {
        this.log(LogLevel.info, tag, msgFn, error);
    }

    debug(tag: string, msgFn: LogMessageFn, error?: unknown): void {
        this.log(LogLevel.debug, tag, msgFn, error);
    }

    trace(tag: string, msgFn: LogMessageFn, error?: unknown): void {
        this.log(LogLevel.trace, tag, msgFn, error);
    }

    getLevelName(): string {
        return LogLevel[this.currentLevel];
    }

    setLevel(level: string): ChangeLevelResult {
        const normalizedLevel = LogLevel[level.toLowerCase()];
        if (!normalizedLevel && normalizedLevel !== LogLevel.off) { // т.к. off = 0 то его проверяем отдельно
            return {
                isSuccess: false,
                message: `Unknown log level: ${level}. Available levels: ${Object.keys(LogLevel)}`
            };
        }
        this.currentLevel = normalizedLevel;
        this.log(LogLevel.info, 'PluginLogger', () => `setLevel Log level changed to: ${LogLevel[normalizedLevel]}`);
        return {
            isSuccess: true,
            message: `log level changed to ${normalizedLevel}`
        };
    }

    private log(level: LogLevel, tag: string, msgFn: LogMessageFn, error?: unknown) {
        if (this.currentLevel >= level) {
            const levelTag = LogLevel[level];
            const message = (logMessageToStringArray(msgFn) || [])
                .join('\n');
            let errorStack: string = undefined;
            if(error instanceof Error){
                errorStack = `| errorStack: ${JSON.stringify(error.stack)}`;
            } else if (error) {
                errorStack = `| errorStack: ${JSON.stringify(error)}`;
            }
            if (window.$PAPI) {
                window.$PAPI.sendLog({
                    level: levelTag,
                    tag: tag,
                    message: message,
                    errorStack: errorStack
                });
            }
        }
    }
}

export function initPluginLogger() {
    changeLoggerImpl(new PluginLogger());
}
