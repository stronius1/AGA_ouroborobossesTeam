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
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025

  Contributors:
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
*/

import env from '@front/helpers/env';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import { v4 as uuidv4 } from 'uuid';
import { HttpHeaders } from '@global/helpers/httpHeaders.mjs';
import {extreactOrgCtxFromWindow, isUriHostEqualBackendHost} from '@front/helpers/orgCtxTools.js';

const logger = getLoggerWithTag('f/h/backend.api.helper');

/**
 * Отправка запроса на любой внешний ресурс
 * в отличие от requests.request('backend://...') не подставляет /core/storage и дает возможность обращаться к любому адресу
 * @param url - адрес куда надо отправить запрос
 * @param options - опции запроса передаются напрямую в fetch (тип запроса, заголовки и прочее)
 * @param statusMapping - мапинг статуса ответа/ошибки
 * @returns {Promise<undefined|any>}
 */
export const handledRequest = async(url, options = {}, statusMapping) => {
    try {
        if (!options.headers) {
            options.headers = {};
        }
        options.headers[HttpHeaders.REQUEST_ID] = uuidv4();
        const orgCtx = extreactOrgCtxFromWindow();
        if (orgCtx && env.backendURL && isUriHostEqualBackendHost(url)) {
            options.headers[HttpHeaders.X_SFA_ORGCTX] = orgCtx;
        }
        const request =  await fetch(url, options);
        const text = !request.ok ? await request.text() : '';
        const response = request.ok ? await request.json() : text ? JSON.parse(text) : undefined;

        if (!request.ok) {
            handleError(response, request.status, statusMapping);
        } else {
            return response;
        }
        return undefined;
    } catch (e) {
        return undefined;
    }
};

/**
 * Запрос к backend просто обертка над handledRequest, чтобы не передавать каждый раз env.backendURL
 * @param relativeUrl - относительный адрес сервиса на backend (относительно базового url env.backendURL)
 * @param options - смотри handledRequest
 * @param statusMapping - смотри handledRequest
 * @returns {Promise<*|undefined>}
 */
export const requestToBackend = async(relativeUrl, options = {}, statusMapping = null) => {
    return handledRequest(env.backendURL + relativeUrl, options, statusMapping);
};

const handleError = (error, code, statusMapping) => {
    if (error) {
        if (code === 500 || code === 409) {
            logger.error(() => `handleError status 500/409: ${statusMapping?.[500] ?? error.message}`);
        } else {
            logger.error(() => `handleError error: ${error?.message}`);
        }
    }
};
