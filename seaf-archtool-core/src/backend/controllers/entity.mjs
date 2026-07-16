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
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
	  R.Piontik <r.piontik@mail.ru> - 2023
	  R.Piontik <r.piontik@mail.ru> - 2024
      Vladislav Nefedov <clay.zenx@gmail.com>, Sber - 2024
*/

// Модуль реализующий доступ к презентациям сущностей как API
// Формат доступа /entities/[Идентификатор сущности]/presentations/[Идентификатор презентации]?[параметры]

import cache from '../storage/cache.mjs';
import datasets from '../helpers/datasets.mjs';
import helpers from './helpers.mjs';
import ajv from 'ajv';
import mustache from 'mustache';
import request from '../helpers/request.mjs';
import md5 from 'md5';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import {getCachePrefixWithDomain} from '@back/helpers/cachePrefixByDomain.mjs';

const LOG_TAG = 'entity-handler';
const logger = getLoggerWithTag(LOG_TAG);

export default function(app) {

    // Рендерит презентацию сущности
    app.get(['/seaf-core/api/entities/:entity/presentations/:presentation', '/entities/:entity/presentations/:presentation'], async(req, res) => {
        // Проверяем, что готовы обрабатывать запросы
        if (!helpers.isServiceReady(app, res)) return;


        const start = Date.now();

        const entityID = req.params.entity;
        const presentationID = req.params.presentation;

        if (!entityID || !presentationID) {
            res.status(400).json({ message: 'Error of URI path /entities/[Entity ID]/presentations/[Presentation ID]?[params]' });
            return;
        }

        // Проверяем есть ли Entity
        const entity = req.storage.manifest?.entities[entityID];
        if (!entity) {
            res.status(404).json({ message: `Not found entity [${entityID}]` });
            return;
        }

        // Проверяем есть ли презентация
        const presentation = (req.storage.manifest.entities[entityID].presentations || {})[presentationID];
        if (!presentation) {
            res.status(404).json({ message: `Not found presentation [${presentationID}] for entity [${entityID}]` });
            return;
        }

        // Определяем тип документа
        const docType = (presentation.type || '').toLowerCase();
        const path = `/entities/${entityID}/presentations/${presentationID}`;
        if (docType !== 'upload') {
            res.status(405).json({ message: `Document type [${docType}] not supported for sever mode. Location [${path}]`});
            return;
        }

        const entityParams = req.query;

        //Проверяем, что есть поле template
        const templateSource = presentation.template;
        // Необязательно
        //if (!templateSource) {
        //    res.status(500).json({ message: `Not found required field [template]. Location [${path}]`});
        //    return;
        //}

        // Проверяем параметры
        if (presentation.params) {
            try {
                const rules = new ajv({ allErrors: true });
                const validator = rules.compile(presentation.params);
                if (!validator(entityParams)) {
                    res.status(400).json({
                        message: `Error of params presentation [${presentationID}] for entity [${entityID}]`,
                        error: validator.errors
                    });
                    return;
                }
            } catch (e) {   
                res.status(500).json({
                    message: `Error schema of params for presentation [${presentationID}] of entity [${entityID}]`,
                    error: e.toString(),
                    params: presentation.params
                });
                return;
            }
        }

        // Получаем данные для генерации ответа
        try {
            const cacheKey = JSON.stringify({entity: entityID, presentation: presentationID, params: entityParams});
            const cachePrefix = getCachePrefixWithDomain(req.storage);
            const data = await cache.pullFromDataCache(cachePrefix, cacheKey, async()=> {
                return await datasets(req.storage).releaseData(path, entityParams);
            }).catch(() => {
                logger.error(() => 'Entity fetch failed');
            });

            // Если шаблон есть, рендерим его
            if (templateSource) {
                const baseURL = req.storage?.md5Map[md5(path)];

                const template = (await request(templateSource, baseURL)).data;
                const content = mustache.render(template, data);

                res.setHeader('Content-Type', presentation.mimetype || 'text/plain').send(content);
            } else {
                res.json(data);
            }
        } catch(e) {
            res.json({
                message: e.message,
                error: e
            });
        }
        logger.trace(() => JSON.stringify({
            userName: req.userProfile?.userName,
            time: Date.now() - start,
            originalUrl: req.originalUrl
        }));
    });
}
