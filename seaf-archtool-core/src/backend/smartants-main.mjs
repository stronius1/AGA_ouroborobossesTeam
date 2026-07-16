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
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2024
*/

import express from 'express';
import md5 from 'md5';
import './helpers/env.mjs';
import compress from '../global/compress/compress.mjs';
import { WorkerStack } from './utils/worker-stack.mjs';

const compressor = compress();

const app = express();
const PORT = global.$smartants.baseUrl.port;
const { maxWorkers, workerTimeout, source } = global.$smartants;

const smartantsWorkerThreads = new WorkerStack(maxWorkers, source, workerTimeout, 100000);

app.get(`/${global.$smartants.pathUrl}:data`, async (req, res) => {
    const query = JSON.parse(await compressor.decodeBase64(req.params.data));
    try {
        const result = await smartantsWorkerThreads.execute({ params: query, queryID: md5(req.params.data) });
        res.send(result);
    } catch (err) {
        res.status(503).send('Smartants internal Error');
    }
});

app.listen(PORT);
