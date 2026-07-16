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
      Vladislav Markin <markinvy@yandex.ru>, Sber

  Contributors:
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2024
*/

import express from 'express';
import {changeLoggerImpl, getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import { parentPort } from 'worker_threads';
import {mainLogger} from '@back/utils/logger/constLoggers.mjs';

changeLoggerImpl(mainLogger);

const LOG_TAG = 'liveness';
const logger = getLoggerWithTag(LOG_TAG);

logger.info(() => `Liveness process node params: ${process.execArgv}; and options: ${process.env.NODE_OPTIONS}`);

const livenessPort = process.env.VUE_APP_DOCHUB_LIVENESS_PORT || 8090;
const app = express();
let status = 'loading';

parentPort.on('message', (message) => {
  (status = message);
});

function startLivenessWorker(app, serverPort) {
  app.get('/health/livez', async(_, res) => {
    return res.status(200).json({ status });
  });

  app.listen(serverPort, () => logger.info(() => `Liveness worker ${process.pid} running on ${serverPort}`));
}

startLivenessWorker(app, livenessPort);
