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
      Vladislav Markin <markinvy@yandex.ru>, Sber

  Contributors:
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2025
*/

// import express from 'express';
import { hasAPIEtag } from '../helpers/env.mjs';
import cors from 'cors';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import {HttpHeaders} from '@global/helpers/httpHeaders.mjs';

const LOG_TAG = 'express_headers';
const logger = getLoggerWithTag(LOG_TAG);

export default function(app) {
  // установка eTag
  if (!hasAPIEtag) {
    app.set('etag', false);
    logger.info(() => 'Express headers eTag are turned off for API');
  }
  // установка CORS заголовков
  app.use(cors());

  app.use(async(req, res, next) => {
    const requestId = req.headers[HttpHeaders.REQUEST_ID];
    if (requestId) {
      res.set(HttpHeaders.REQUEST_ID, requestId);
    }
    next();
  });
}





