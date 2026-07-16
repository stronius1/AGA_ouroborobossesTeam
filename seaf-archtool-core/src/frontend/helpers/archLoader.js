/*
  Copyright (C) 2026 Sber

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
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2026

  Contributors:
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2026
*/

import gateway from '@ide/gateway';
import {Plugins} from '@front/helpers/env';
import env from '@front/helpers/env';
import datasets from '@front/helpers/datasets.js';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

const logger = getLoggerWithTag('f/h/archLoader');

const actionName = 'sendArch';

export function registerArchLoadEvent() {
    if (env.isPlugin(Plugins.idea)) {
        logger.info(() => `papi listener for event ${actionName} registered`);
        gateway.appendListener(actionName, (data) => {
            logger.debug(() => [
                'Receive request for dataset data',
                {title: 'actionName', obj: actionName},
                {title: 'data', obj: data}
            ]);
            const payload = data?.payload ? JSON.parse(data.payload) : undefined;
            const datasetName = payload?.datasetName;
            const traceId = payload?.traceId;
            if (!payload || !datasetName || !traceId) {
                const message = `Required request attributes were not passed. payload=${Boolean(payload)}` +
                    `, payload.datasetName=${Boolean(payload?.datasetName)}, payload.traceId=${Boolean(payload?.traceId)}`;
                logger.error(() =>`${traceId}: ${message}`);
                window.$PAPI.archLoad({
                    traceId: traceId,
                    errorMessage: message
                });
                return;
            }
            logger.info(() => `${traceId}: Receive request for dataset data ${datasetName}`);
            datasets().getData(null, {
                origin: datasetName,
                source: '($)'
            }).then((datasetData) => {
                logger.trace(() => [
                    `${traceId}: dataset data of ${datasetName}`,
                    {title: 'dataset', obj: datasetData}
                ]);
                logger.info(() => `${traceId}: Dataset data of ${datasetName} success calculated and send to plugin by papi`);
                window.$PAPI.archLoad({
                    traceId: traceId,
                    datasetData: datasetData
                });
            }).catch((err) => {
                const message = `Error when get data of dataset ${datasetName}`;
                logger.error(() => [
                    `${traceId}: ${message}`,
                    {title: 'actionName', obj: actionName}
                ], err);
                window.$PAPI.archLoad({
                    traceId: traceId,
                    errorMessage: message
                });
            });
        });
    } else {
        logger.info(() => `Слушатель для события ${actionName} НЕ зарегистрирован т.к. запущены не в idea`);
    }
}
