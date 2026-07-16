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
      Temnyakov Nikolay <temnjakovn@gmail.com>, Sber - 2025
*/

import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

const LOG_TAG =  'config-validator';
const logger = getLoggerWithTag(LOG_TAG);

const regex = {
    iss: /^https?:\/\/[^\s/]+(?:\/[^\s]*)?$/,       // Проверяем базовый URL с необязательным путем
    path: /^\/[^\s]*$/,                             // Для logoutPath
    alphanum: /^[a-zA-Z0-9_-]+$/,                   // Разрешить буквы, цифры, тире и подчеркивания
    label: /^[А-ЯЁа-яёA-Za-z0-9\-\s_]+$/            // Разрешить кириллицу, латиницу, цифры, тире, подчеркивания, пробелы
};


function parseEnvJson(key) {
    try {
        return JSON.parse(process.env[key] || '[]');
    } catch (e) {
        logger.info(() => `Invalid JSON in ${key}: ${e.message}`);
        return [];
    }
}

function validateAuthUserConfig(config) {
    return config.filter((entry, idx) => {
        let valid = true;

        if (typeof entry.iss !== 'string' || !regex.iss.test(entry.iss)) {
            logger.error(() => `Invalid "iss" in VUE_APP_DOCHUB_AUTH_USER_CONFIG (entry ${idx}): ${entry.iss}`);
            valid = false;
        }

        if (typeof entry.surname !== 'string' || !regex.alphanum.test(entry.surname)) {
            logger.error(() => `Invalid "surname" in VUE_APP_DOCHUB_AUTH_USER_CONFIG (entry ${idx}): ${entry.surname}`);
            valid = false;
        }

        if (typeof entry.name !== 'string' || !regex.alphanum.test(entry.name)) {
            logger.error(() => `Invalid "name" in VUE_APP_DOCHUB_AUTH_USER_CONFIG (entry ${idx}): ${entry.name}`);
            valid = false;
        }

        if (typeof entry.role !== 'string' || !regex.alphanum.test(entry.role)) {
            logger.error(() => `Invalid "role" in VUE_APP_DOCHUB_AUTH_USER_CONFIG (entry ${idx}): ${entry.role}`);
            valid = false;
        }

        if (typeof entry.userId !== 'string' || !regex.alphanum.test(entry.userId)) {
            logger.error(() => `Invalid "userId" in VUE_APP_DOCHUB_AUTH_USER_CONFIG (entry ${idx}): ${entry.userId}`);
            valid = false;
        }

        return valid;
    });
}


function validateRolesConfig(config) {
    return config.filter((entry, idx) => {
        const validRole = !entry.role || regex.alphanum.test(entry.role);
        const validLabel = !entry.label || regex.label.test(entry.label);

        if (!validRole || !validLabel) {
            logger.error(() => `Invalid configuration in .env file at parameter: VUE_APP_DOCHUB_ROLES_CONFIG (entry ${idx}). The entry value is invalid: ${JSON.stringify(entry)}. Please verify that the entry conforms to the expected structure and all required fields are provided.`);
        }

        return true;
    });
}

function validateLogoutConfig(config) {

    if (!Array.isArray(config)) {
        logger.error(() => `VUE_DOCHUB_AUTH_LOGOUT_CONFIG must be an array, got: ${typeof config}`);
        return [];
    }

    const allowedTypes = ['tokenHint', 'clientId', 'proxy'];

    return config.filter((entry, idx) => {
        let valid = true;

        if (typeof entry.iss !== 'string' || !regex.iss.test(entry.iss)) {
            logger.error(() => `Invalid "iss" in VUE_DOCHUB_AUTH_LOGOUT_CONFIG (entry ${idx}): ${entry.iss}`);
            valid = false;
        }

        if (typeof entry.logoutPath !== 'string' || !regex.path.test(entry.logoutPath)) {
            logger.error(() => `Invalid "logoutPath" in VUE_DOCHUB_AUTH_LOGOUT_CONFIG (entry ${idx}): ${entry.logoutPath}`);
            valid = false;
        }

        if (typeof entry.type !== 'string' || !allowedTypes.includes(entry.type)) {
            logger.error(() => `Invalid "type" in VUE_DOCHUB_AUTH_LOGOUT_CONFIG (entry ${idx}). Expected one of ${JSON.stringify(allowedTypes)}, got: ${entry.type}`);
            valid = false;
        }

        if (entry.type === 'clientId') {
            if (typeof entry.clientId !== 'string' || !regex.alphanum.test(entry.clientId)) {
                logger.error(() => `Invalid or missing "clientId" in VUE_DOCHUB_AUTH_LOGOUT_CONFIG (entry ${idx}) for type="clientId": ${entry.clientId}`);
                valid = false;
            }
        }

        return valid;
    });
}

export function loadValidatedConfigs() {
    const authUserRaw = parseEnvJson('VUE_APP_DOCHUB_AUTH_USER_CONFIG');
    const rolesRaw = parseEnvJson('VUE_APP_DOCHUB_ROLES_CONFIG');
    const logoutRaw = parseEnvJson('VUE_DOCHUB_AUTH_LOGOUT_CONFIG');

    const authUserConfig = authUserRaw.length ? validateAuthUserConfig(authUserRaw) : [];

    const rolesConfig = rolesRaw.length ? validateRolesConfig(rolesRaw) : [];

    const logoutConfig = logoutRaw.length ? validateLogoutConfig(logoutRaw) : [];

    return {
        authUserConfig,
        rolesConfig,
        logoutConfig
    };
}
