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
import {JSONPath} from 'jsonpath-plus';

const LOG_TAG =  'account';
const logger = getLoggerWithTag(LOG_TAG);

const defaultFieldMapping = {
    name: '',
    surname: '',
    roles: 'roles',
    userId: 'userId'
};

const parseConfigEnv = (configEnvVar) => {
    const raw = process.env[configEnvVar];
    logger.trace(() => [
        `envName: ${configEnvVar}`,
        `raw Data: ${raw}`
    ]);

    if (!raw) {
        logger.error(() => `Environment variable ${configEnvVar} is not set`);
        return null;
    }

    try {
        return JSON.parse(raw);
    } catch (error) {
        logger.error(() => `Failed to parse JSON in ${configEnvVar}: ${error.message}`);
        return null;
    }
};

const getConfigForIssuer = (parsedConfig, issuer, configType) => {
    if (!Array.isArray(parsedConfig)) {
        logger.error(() => `${configType} configuration is not an array`);
        return null;
    }

    const providerConfig = parsedConfig.find((p) => p.iss === issuer);

    if (!providerConfig) {
        logger.error(() => `${configType} config not found for issuer "${issuer}"`);
        return null;
    }
    return providerConfig;
};

const VUE_APP_DOCHUB_AUTH_USER_CONFIG_PARSED = parseConfigEnv('VUE_APP_DOCHUB_AUTH_USER_CONFIG');
const VUE_APP_DOCHUB_ROLES_CONFIG_PARSED = parseConfigEnv('VUE_APP_DOCHUB_ROLES_CONFIG');

export const getUserConfigForIssuer = (issuer) => {
    return getConfigForIssuer(VUE_APP_DOCHUB_AUTH_USER_CONFIG_PARSED, issuer, 'User info');
};

const translateRole = (role) => {
    const roleMapping = VUE_APP_DOCHUB_ROLES_CONFIG_PARSED.find(r => r.role === role);
    return roleMapping ? toLowerCase(roleMapping.label) : null;
};

const computeInitials = (name, surname) => {
    const nameNorm = normalize(name);
    const surnameNorm = normalize(surname);

    if (nameNorm && surnameNorm) {
        return `${nameNorm[0]}${surnameNorm[0]}`.toUpperCase();
    } else if (nameNorm) {
        return nameNorm[0].toUpperCase();
    } else if (surnameNorm) {
        return surnameNorm[0].toUpperCase();
    }
    return null;
};

const normalize = (value) => {
    return typeof value === 'string' && value !== 'NULL' ? value : null;
};

const toLowerCase = (str) => {
    return str.toLowerCase();
};

const getJsonPathValue = (obj, pathExpr) => {
    try {
        const result = JSONPath({ path: pathExpr, json: obj });
        return result.length === 1 ? result[0] : result;
    } catch (e) {
        return null;
    }
};

export const extractUserData = (payload) => {

        const iss = payload['iss'];
        const config = getUserConfigForIssuer(iss) || defaultFieldMapping;
        logger.trace(() => `user data config: ${JSON.stringify(config)}`);

        const userId = getJsonPathValue(payload, config.userId) || defaultFieldMapping.userId;
        const name = getJsonPathValue(payload, config.name) || defaultFieldMapping.name;
        const surname = getJsonPathValue(payload, config.surname) || defaultFieldMapping.surname;

        let roles = getJsonPathValue(payload, config.roles) || [];
        if (!Array.isArray(roles)) {
            roles = [roles].filter(Boolean);
        }

        const initials = computeInitials(name, surname);

        const translatedRoles = roles.map(role => translateRole(role)).filter(label => label !== null);

        return {
            userId,
            name,
            surname,
            roles: translatedRoles,
            initials
        };
};
