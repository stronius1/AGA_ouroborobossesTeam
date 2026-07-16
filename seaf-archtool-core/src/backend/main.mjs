/*
  Copyright (C) 2021 owner Roman Piontik R.Piontik@mail.ru
  Copyright (C) 2022 Sber

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

  In any derivative products, you must retain the information of
  owner of the original code and provide clear attribution to the project

  https://dochub.info

  The use of this product or its derivatives for any purpose cannot be a secret.


  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.

  Maintainers:
      R.Piontik <r.piontik@mail.ru>

  Contributors:
      R.Piontik <r.piontik@mail.ru> - 2023
      Vladislav Nefedov <clay.zenx@gmail.com>, Sber - 2024
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2024
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
      Nikolay Temnyakov <temnjakovn@gmail.com>, Sber - 2024
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2025
*/


import { v4 as uuidv4 } from 'uuid';
import './helpers/env.mjs';
import storeManager from './storage/manager.mjs';
import express from 'express';
import middlewareCompression from './middlewares/compression.mjs';
import controllerStatic from './controllers/static.mjs';
import controllerCore from './controllers/core.mjs';
import controllerSearch from './controllers/search.mjs';
import controllerStorage from './controllers/storage.mjs';
import controllerEntity from './controllers/entity.mjs';
import controllerSmartants from './controllers/smartants.mjs';
import controllerLogger from './controllers/logger.mjs';
import controllerProbes from './controllers/probes.mjs';
import controllerGigachat from './controllers/gigachat.ts';
import middlewareHeaders from './middlewares/headers.mjs';
import middlewareAccess from './middlewares/access.mjs';
import middlewareManifest from './middlewares/manifestFromCache.mjs';
import parseTokenMiddleware from './middlewares/parseTokenMiddleware.mjs';
import manifestMutator from './controllers/manifestMutator.mjs';
import recorder from './utils/logger/perf-recorder.mjs';
import {registerJsonataVersionFunction} from './helpers/jsonata/versionsFunc.mjs';
import {changeLoggerImpl, getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import {mainLogger} from '@back/utils/logger/constLoggers.mjs';

if (global.$logger.profileEnable) recorder.start();

const app = express();
app.isCluster = false;
app.use(express.json());
const serverPort = process.env.VUE_APP_DOCHUB_BACKEND_PORT || 3030;

//регистрируем основной логгер
changeLoggerImpl(mainLogger);

const logger = getLoggerWithTag('server');

// Актуальный манифест
app.storage = null;

// Подключаем контролер доступности
controllerProbes(app);

// Управляем заголовками
middlewareHeaders(app);

parseTokenMiddleware(app);

// Подключаем контроль доступа
middlewareAccess(app);

middlewareManifest(app);

registerJsonataVersionFunction();

// Основной цикл приложения
const mainLoop = async function() {
    const runUuid = uuidv4();
    // Загружаем манифест
    const server = app.listen(serverPort, function() {
        logger.info(() => `[${runUuid}] DocHub server running on ${serverPort}, wait message: "[${runUuid}] The application is ready...", maybe before`);
    });

    server.setTimeout(500000);

    await storeManager.reloadManifest()
        .then(async(storage) => {
            storage.warmupNeeded = true;
            app.storage = await storeManager.applyManifest(storage);

            // Подключаем сжатие контента
            middlewareCompression(app);

            // API ядра
            controllerCore(app);

            // API поиска по озеру
            controllerSearch(app);

            // API сущностей
            controllerEntity(app);

            // Smartants
            controllerSmartants(app);

            // Контроллер доступа к файлам в хранилище
            controllerStorage(app);

            // Контроллер логирования
            controllerLogger(app);

            // Мутатор манифеста
            if (process.env.MANIFEST_MUTATION === 'y') {
                manifestMutator(app);
            }

            // Gigachat API
            await controllerGigachat(app);

            // Статические ресурсы
            controllerStatic(app);

            app.isReady = true;
            logger.info(() => `[${runUuid}] The application is ready to accept requests`);
        }).catch(err => {
            app.isReady = false;
            app.errorMessage = err.message;
            logger.error(() => `[${runUuid}] Error when start app`, err);
        });
};

await mainLoop();
