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
      Sergeev Viktor, Sber - 2026

  Contributors:
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2026
*/

/**
 * Хранилище прав пользователя
 * Права в данном случае объект права на архитектуру (permission + alias + permission level)
 */
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import env from '@front/helpers/env';
import {requestToBackend} from '@front/helpers/backend.api.helper.js';

const logger = getLoggerWithTag('userRightStore');

/**
 * @type {Array<Object>}
 */
let currentUserRight;
let currentCtx;

async function fetchUserRightData() {
    if (env.isBackendMode) {
        currentUserRight = await requestToBackend('/seaf-core/api/core/user/rights');
    } else {
        currentUserRight = [];
    }
}


const userRightStore = {

    /**
     * Инициализация данных о правах пользователя
     * @returns {Promise}
     */
    async initRightData() {
        try {
            await fetchUserRightData();
            logger.debug(() => ['Right data loaded', {title: 'rights', obj: currentUserRight}]);
        } catch (error) {
            logger.error('Failed to initialize user after login:', error);
        }
    },

    setCurrentCtx(alias) {
        if (alias) {
            currentCtx = alias;
        } else {
            currentCtx = currentUserRight?.at(0)?.alias;
        }
    },

    getFirstUserCtxAlias() {
        return currentUserRight?.at(0)?.alias;
    },

    getCurrent() {
        return currentUserRight.find(el => el.alias === currentCtx);
    },

    getAll() {
        return currentUserRight;
    }
};

export default userRightStore;
