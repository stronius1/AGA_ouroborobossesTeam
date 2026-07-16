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
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2024
	  R.Piontik <r.piontik@mail.ru> - 2023
      Temnyakov Nikolay <temnjakovn@gmail.com>, Sber - 2024
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
      Vladislav Markin, Sber - 2026
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2026
*/

import request from '../helpers/request.mjs';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import { envelopeDocument } from '@global/helpers/api/envelope.js';
import { checkIsAbsoluteBitbucketPath } from '@back/helpers/checkIsAbsoluteBitbucketPath.mjs';
import { HttpError } from '@back/helpers/httpError.mjs';
import { createRepositoryIDfromURI } from '@global/manifest/parser3/helpers.mjs';

const LOG_TAG = 'controller-storage';
const logger = getLoggerWithTag(LOG_TAG);
const _baseUrlV1 = '/seaf-core/api/core/storage';
const _baseUrlV2 = '/core/storage';

async function requestToStorage(req, res, reqBaseUrl) {
    const hash = req.params.hash || '$unknown$';
    let url = req.originalUrl.slice(`${reqBaseUrl}/${hash}/`.length).replace(/%E2%86%90/g, '..');
    let uri = url.split('?')[0];
    const baseURL = req.storage?.md5Map[hash];

    const isAbsolutePath = checkIsAbsoluteBitbucketPath(uri);
    if (isAbsolutePath) {
        try {
            uri = uri.slice(1);
            url = uri.split('@')[1].split('/').at(-1);

            const repositoryID = createRepositoryIDfromURI(uri);

            const repositorySources = Array.isArray(req.storage?.repositorySources) ? req.storage.repositorySources : [];
            const isImported = repositorySources.includes(repositoryID);
            if (!isImported) {
                throw new HttpError(`Репозиторий файла ${uri} не используется в манифесте!`, 400);
            }
        } catch (e) {
            const statusCode = typeof (e?.status) === 'number' ? e.status : 500;
            return res.status(statusCode).json({
                message: e.message,
                error: e
            });
        }
    }

    const envelope = req.query?.envelope;
    logger.trace(() => `Request to storage ${req.originalUrl}`);
    if (req.query?.inlineContent && !uri && baseURL) { //в запросе есть флаг, что контент вложенный и не передан uri, используем только baseURL
        if (envelope) {
            try {
                const result = await request(baseURL, null);
                res.status(200).json(envelopeDocument({
                    data: typeof result.data === 'string'
                        ? result.data
                        : JSON.stringify(result.data)
                }));
            } catch (e) {
                res.status(500).json({
                    message: e.message,
                    error: e
                });
            }
        } else {
            request(baseURL, null, res)
                .catch((e) => res.status(500).json({
                    message: e.message,
                    error: e
                }));
        }
    } else if (!baseURL || !uri) { // иначе если нет одно из путей, то не сможем обработать запрос, возвращаем ошибку
        res.status(403).json({
            error: 'Access denied'
        });
    } else {
        if (envelope) {
            try {
                const result = await request(uri, baseURL);
                res.status(200).json(envelopeDocument({
                    data: typeof result.data === 'string'
                        ? result.data
                        : JSON.stringify(result.data)
                }));
            } catch (e) {
                res.status(500).json({
                    message: e.message,
                    error: e
                });
            }
        } else {
            request(uri, baseURL, res)
                .catch((e) => res.status(500).json({
                    message: e.message,
                    error: e
                }));
        }
    }
}

export default (app) => {
    // Проксирует запрос к хранилищу
    // V1 оставлена до совместимости см manifestNeedChecker.mjs
    app.get(_baseUrlV1 + '/:hash/*', async function(req, res) {
        await requestToStorage(req, res, _baseUrlV1);
    });

    app.get(_baseUrlV2 + '/:hash/*', async function(req, res) {
        await requestToStorage(req, res, _baseUrlV2);
    });
};
