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

import md5 from 'md5';
import cache from '../storage/cache.mjs';
import compress from '../../global/compress/compress.mjs';
import { WorkerStack } from '../utils/worker-stack.mjs';

const compressor = compress();
const { source, maxWorkers, workerTimeout, mode } = global.$smartants;
const smartantsWorkerThreads = mode === 'thread' ? new WorkerStack(maxWorkers, source, workerTimeout, 500000) : null;

export default function(app) {
    app.get(['/seaf-core/api/smartants/:data', '/smartants/:data'], (req, res) => {
        cache.pullFromDataCache('smartants', req.params.data, async () => {
            if (mode === 'service') {
                return (
                    fetch(new URL(encodeURIComponent(req.params.data), global.$smartants.baseUrl))
                    .then((res) => res.json())
                    .catch((err) => ({ message: err }))
                );
            } else if (mode === 'thread') {
                const query = JSON.parse(await compressor.decodeBase64(req.params.data));
                return await smartantsWorkerThreads.execute({ params: query, queryID: md5(req.params.data) });
            }
        }).then((result) => {
            if (result?.result !== 'OK') {
                res.status(503).send({ message: 'Smartants Error', result });
            } else {
                res.send(result);
            }
        }).catch((err) => {
            res.status(503).send({ message: 'Smartants Error', result: err });
        });
    });
}
