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
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2025
*/

import { KJUR } from 'jsrsasign';
import { getLoggerWithTag } from '@global/logger/v2/logger.mjs';
import { performanceLogger } from '@back/utils/logger/index.mjs';

const SIGNING_ALGORITHM = 'RS256';
const LOG_TAG = 'b/m/ptm';
const logger = getLoggerWithTag(LOG_TAG);
const perfLogger = performanceLogger?.getGenericLogger();

const parseTokenMiddleware = (req, _res, next) => {
  const useDebugToken = typeof process.env.VUE_APP_DEBUG_SEAF_TOKEN === 'string';
  const jwt = useDebugToken ? process.env.VUE_APP_DEBUG_SEAF_TOKEN : req.headers?.authorization?.slice('Bearer '.length);
  if (typeof jwt === 'string' && jwt.trim() && !jwt.includes('undefined')) {
    try {
      perfLogger?.setStart();
      if (useDebugToken || KJUR.jws.JWS.verifyJWT(jwt, process.env.VUE_APP_DOCHUB_AUTH_PUBLIC_KEY, { alg: [SIGNING_ALGORITHM] })) {
        const parsedJWT = KJUR.jws.JWS.parse(jwt);
        req.tokenPayload = parsedJWT;
        logger.trace(() => `Parsed JWT: ${JSON.stringify(parsedJWT, null, 2)}`);
      } else {
        logger.warn(() => `JWT signature is not verified. JWT: ${JSON.stringify(jwt)}`);
      }
    } catch (e) {
      logger.warn(() => `User info retrieve error: ${e}`);
    } finally {
      perfLogger?.setEnd();
    }
  } else {
    logger.trace(() => 'JWT not found');
  }
  next();
};

export default (app) => {
  app.use(parseTokenMiddleware);
};
