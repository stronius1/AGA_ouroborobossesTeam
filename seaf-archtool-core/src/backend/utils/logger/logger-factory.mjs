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

import winston from 'winston';
import { threadId } from 'worker_threads';
import cluster from 'node:cluster';
import '../../helpers/env.mjs';
import {logMessageToStringArray} from '@global/logger/v2/logMessageToStringArray.mjs';
import colorspace from 'colorspace';

//TODO выпилить вместе со временным импортом, когда colorspace или winston подтянуться по color без уязвимостей
await colorspace.initColor();

const loggingLevels = {
	levels: {
		off: 0,
		error: 1,
		warn: 2,
		info: 3,
		debug: 4,
		trace: 5
	}
};

/**
 * Создаем новый логгер, внутри winston и оборачиваем его в api SeafLogger
 * @param config
 */
export function newLogger(config) {
	const id = `${process.pid}_${threadId}`;
	const workerInfo = cluster.isWorker ? `[w_${id}]` : `[m_${id}]`; // Indicate if it's a worker or master process

	const loggingTransports = [];

	if (config?.enableConsoleLog ?? true) {
		loggingTransports.push(new winston.transports.Console({
			level: config.consoleLevel
		}));
	}
	if (config?.logFileName) {
		loggingTransports.push(new winston.transports.File({
			filename: config.logFileName, 
			level: config.fileLevel
		}));
	}
	const loggingFormat = winston.format.printf(({ level, message, timestamp }) => {
		return `${timestamp} ${workerInfo}: [${level}]: ${message}`;
	});
	if (loggingTransports.length < 1) {
		return undefined;
	}


	const logger = winston.createLogger({
		levels: loggingLevels.levels,
		level: config?.defaultLevel,
		format: winston.format.combine(
			winston.format.timestamp(),
			winston.format.splat(),
			loggingFormat
		),
		transports: loggingTransports,
		exceptionHandlers: loggingTransports
	});

	function log(level, tag, msgFn, error) {
		try {
			if (logger.isLevelEnabled(level)) {
				const message = (logMessageToStringArray(msgFn) || [])
					.join(' | ');
				let errorStack = '';
				if(error instanceof Error){
					errorStack = `| errorStack: ${JSON.stringify(error.stack)}`;
				} else if(error) {
					errorStack = `| errorStack: ${JSON.stringify(error)}`;
				}
				logger.log(level, `${tag}: ${message} ${errorStack}`);
			}
		} catch (e) {
			// других вариантов кроме как вывести ошибку в консоль нету
			// eslint-disable-next-line no-console
			console.log('error when try write log', e);
		}
	}


	const validLevels = Object.keys(loggingLevels.levels);
	const validLevelsAsString = validLevels.join(', ');
	return {
		error: (tag, msgFn, error) =>  log('error', tag, msgFn, error),
		warn: (tag, msgFn, error) => log('warn', tag, msgFn, error),
		info: (tag, msgFn, error) => log('info', tag, msgFn, error),
		debug: (tag, msgFn, error) => log('debug', tag, msgFn, error),
		trace: (tag, msgFn, error) => log('trace', tag, msgFn, error),
		setLevel: (level) => {
			if (validLevels.includes(level)) {
				logger.level = level;
				return {
					isSuccess: true,
					message: `Установлен уровень ${level}`
				};
			} else {
				return {
					isSuccess: false,
					message: `Параметр "${level}" не соответствует константам. Возможные значения: ${validLevelsAsString}`
				};
			}
		},
		getLevelName: () => logger.level
	};
}
