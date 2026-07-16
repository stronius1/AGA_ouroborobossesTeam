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
      Temnyakov Nikolay <temnjakovn@gmail.com>, Sber

  Contributors:
      Temnyakov Nikolay <temnjakovn@gmail.com>, Sber - 2025
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
*/

import {handledRequest} from '@front/helpers/backend.api.helper.js';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

const logger = getLoggerWithTag('f/c/U/l/h/api.helper');

const notifySuccess = (successMsg, data) => {
    const msgText = typeof successMsg === 'function' ? successMsg(data) : successMsg;
    logger.info(() => msgText);
};

export async function uploadFile(url, formData, statusMapping) {
    return await handledRequest(url, {
        method: 'POST',
        headers: {
            'Access-Control-Allow-Origin': '*'
            // 'Content-Type': 'multipart/form-data'
        },
        body: formData
    }, statusMapping).then((result) => {
        if (result && statusMapping?.successMsg) notifySuccess(statusMapping.successMsg, result);
        return result;
    });
}
