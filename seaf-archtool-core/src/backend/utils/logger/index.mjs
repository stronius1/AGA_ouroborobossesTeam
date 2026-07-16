/*
  Copyright (C) 2023 Sber

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
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber

  Contributors:
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
*/

import { PerformanceLogger } from './perf-logger.mjs';
import performanceRecorder from './perf-recorder.mjs';
import {getLogger} from '@global/logger/v2/logger.mjs';
import {jsonataLogger} from '@back/utils/logger/constLoggers.mjs';

const performanceLoggerEnabled = process.env.VUE_APP_DOCHUB_PERF_LOGGER_ENABLE?.toLowerCase() === 'on';

const logger = getLogger();

const performanceLogger = performanceLoggerEnabled ? new PerformanceLogger(logger, performanceRecorder) : null;
const jsonataPerformanceLogger = performanceLoggerEnabled ? new PerformanceLogger(jsonataLogger, performanceRecorder) : null;


export { jsonataLogger, logger, performanceLogger, jsonataPerformanceLogger };
