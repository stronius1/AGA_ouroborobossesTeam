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
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2023
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2025
      Alexander Romashin <romashin.a.va@sberbank.ru>, Sber - 2025
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2026
*/

import path from 'path';
import fs from 'fs';
import axios from 'axios';
import yaml from 'yaml';
import uriTool from './uri.mjs';
import gitlab from './gitlab.mjs';
import bitbucket from './bitbucket.mjs';
import { performanceLogger } from '../utils/logger/index.mjs';
import xml from '@global/helpers/xmlparser.mjs';
import './env.mjs';
import https from 'node:https';
import http from 'node:http';
import { hasStaticEtag } from '../helpers/env.mjs';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

const DEFAULT_REQUEST_TIMEOUT = 60000;
const MAX_REQUEST_TIMEOUT = 300000;
const REQUEST_TAG = 'request';
const logger = getLoggerWithTag(REQUEST_TAG);

if (global.$httpRepeater.maxSockets) {
    https.globalAgent.maxSockets = http.globalAgent.maxSockets = global.$httpRepeater.maxSockets;
}

if (process.env.VUE_APP_DOCHUB_GITLAB_URL) {
    // Подключаем интерцептор авторизации GitLab
    axios.interceptors.request.use(gitlab.axiosInterceptor);
} else if (process.env.VUE_APP_DOCHUB_BITBUCKET_URL) {
    // Подключаем интерцептор авторизации BitBucket
    axios.interceptors.request.use(bitbucket.axiosInterceptor);
}

// Здесь разбираемся, что к нам вернулось из запроса и преобразуем к формату внутренних данных
axios.interceptors.response.use(
    (response) => {
        if (typeof response.data === 'string') {
            if (!response.config.raw) {
                const mimeType = response.headers['content-type'];
                const url = response.config.url.split('?')[0].toLowerCase();
                if (['application/json', 'text/json'].includes(mimeType) || url.indexOf('.json/raw') >= 0 || url.endsWith('.json'))
                    response.data = JSON.parse(response.data);
                else if (['application/yaml', 'application/x-yaml', 'text/yaml', 'text/x-yaml'].includes(mimeType) || url.indexOf('.yaml/raw') >= 0 || url.endsWith('.yaml'))
                    response.data = yaml.parse(response.data);
                else if (['application/xml', 'text/xml'].includes(mimeType) || (url.indexOf('.xml/raw') >= 0) || url.endsWith('.xml'))
                    response.data = xml.parse(response.data);
            }
        }
        return response;
    }
);

// Проверяет разрешен ли путь к файлу
function isAvailablePath(path) {
    // eslint-disable-next-line no-undef
    return path.startsWith(`${$paths.file_storage}/`);
}

const CONTENT_TYPE_YAML = 'application/x-yaml';
const CONTENT_TYPE_JSON = 'application/json';
const CONTENT_TYPE_XML = 'application/xhtml+xml';

// Определяет тип контента
function getContentType(url, result) {
    let contentType = null;
    const uri = url.split('?')[0];
    if (uri.endsWith('.yaml') || uri.endsWith('.yml') || (uri.indexOf('.yaml/raw') >= 0) || (uri.indexOf('.yml/raw') >= 0)) {
        contentType = CONTENT_TYPE_YAML;
    } else if (uri.endsWith('.json') || (uri.indexOf('.json/raw') >= 0)) {
        contentType = CONTENT_TYPE_JSON;
    } else if (uri.endsWith('.xml') || (uri.indexOf('.xml/raw') >= 0)) {
        contentType = CONTENT_TYPE_XML;
    } else if (result) {
        contentType = result?.headers?.['content-type'] ?? null;
    }
    return contentType;
}

function parseFileData(contentType, fileData) {
    try {
        if (contentType === CONTENT_TYPE_YAML) {
            return yaml.parse(fileData);
        } else if (contentType === CONTENT_TYPE_JSON) {
            return JSON.parse(fileData);
        } else if (contentType === CONTENT_TYPE_XML) {
            return xml.parse(fileData);
        }
    } catch (e) {
        logger.debug(() => `Can't parse content type ${contentType}`);
    }

    return fileData;
}

// Выполняет запрос по URL
//  url         - ссылка на ресурс
//  baseUIR     - базовый URI 
//  response    - Express response. Если установлен, то запрос будет работать как прокси.
async function request(url, baseURI, response, params = {}, attempt = 0) {
    const requestLogger = attempt === 0 ? performanceLogger?.getRequestLogger(url) : null;
    requestLogger?.setStart();
    // Разбираем URL
    let uri = null;
    if (baseURI) {
        uri = uriTool.makeURL(url, baseURI).url;
    } else {
        uri = new URL(url);
    }
    logger.trace(() => `request ro url ${uri}`);
    // Если локальное файловое хранилище
    if (uri.protocol === 'file:') {
        // eslint-disable-next-line no-undef
        const fileName = path.join($paths.file_storage, decodeURIComponent(uri.pathname));
        logger.trace(() => `request file with name ${fileName}`);
        if (!isAvailablePath(fileName)) {
            throw `File [${fileName}] is not available.`;
        }
        const contentType = getContentType(fileName);
        if (response) {
            contentType && response.setHeader('content-type', contentType);
            return response.sendFile(fileName, {etag: hasStaticEtag});
        } else {
            const result = {
                data: parseFileData(contentType, fs.readFileSync(fileName, {encoding: 'utf8', flag: 'r'}))
            };
            requestLogger?.setEnd();
            return result;
        }
    }
    // Если запрос по http / https
    else if ((uri.protocol === 'http:') || (uri.protocol === 'https:')) {
        const url = uri.toString();
        if (response) {
            let result = null;
            try {
                result = await axios({url, responseType: 'stream', ...params}).finally(() => requestLogger?.setEnd());
                const contentType = getContentType(url, result);
                contentType && response.setHeader('content-type', contentType);
                return result.data.pipe(response);
            } catch (e) {
                logger.error(() => `Error of request [${url}] with error [${e.message}]`);
                response.status(e?.response?.status || 500);
                response.json({
                    error: 'Error of request to original source.'
                });
            }
            requestLogger?.setEnd();
            return result;
        } else
            return await axios({url, ...params})
                // Кетч добавлен из-за проблем с BitBucket.
                .catch((err) => {
                    if (err?.response?.status !== 404 && attempt < global.$httpRepeater.maxRetries) {
                        return new Promise((resolve) => {
                            const timeout = Math.min((params?.timeout || DEFAULT_REQUEST_TIMEOUT) * ++attempt, MAX_REQUEST_TIMEOUT);
                            setTimeout(
                                () => resolve(request(url, baseURI, response, {...params, timeout}, attempt)),
                                Math.floor(Math.random() * (3000 + 3000 * attempt) + 1500)
                            );
                        });
                    }
                    return Promise.reject(err);
                })
                .finally(() => requestLogger?.setEnd());
    }
    // Если запрос к GitLab
    else if (uri.protocol === 'gitlab:') {
        return request(uriTool.makeURL(uri).url, baseURI, response);
    }
    // Если запрос к BitBucket
    else if (uri.protocol === 'bitbucket:') {
        return request(uriTool.makeURL(uri).url, baseURI, response);
    }
    // eslint-disable-next-line no-console
    throw `Can not processing protocol [${uri.protocol}] for url=[${url}]`;
}

export default request;
