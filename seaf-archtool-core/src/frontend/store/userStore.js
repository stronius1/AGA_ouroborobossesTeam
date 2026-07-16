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
      Sergeev Viktor, Sber - 2025

  Contributors:
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
*/

/**
 * Обертка над функционалом авторизации, которая дает доступ к данным авторизации и прячет за собой логику работы с
 * провайдером авторизации
 */
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import requests from '@front/helpers/requests';
import env from '@front/helpers/env';
import oidcClient from '@front/auth/oidc-client.js';

const logger = getLoggerWithTag('userStore');

let currentUser;

async function fetchUserData() {
    const response = await requests.request(`${env.backendURL}/core/user-info`);
    const profile = response.data?.user;
    currentUser = {
        name: profile?.name,
        surname: profile?.surname,
        roles: Array.isArray(profile?.roles) ? profile.roles : [],
        initials: profile?.initials,
        userId: profile?.userId || null
    };
}

function clearUserData() {
    currentUser = null;
}


export const userStore = {

    /**
     * Инициализация данных о пользователе
     * @returns {Promise}
     */
    async initUserData() {
        if (!env.isBackendMode) {
            currentUser = null;
            return;
        }
        const userData = await oidcClient.getUser();
        if (!userData) {
            logger.debug(() => 'No auth user');
            return;
        }
        try {
            // Запрашиваем данные пользователя
            await fetchUserData();
            logger.debug(() => 'User data loaded after login:', currentUser);
        } catch (error) {
            logger.error('Failed to initialize user after login:', error);
        }
    },

    async login() {
        await oidcClient.login();
    },

    async signinCallback() {
        await oidcClient.signinCallback();
    },

    async logout() {
        clearUserData();
        await oidcClient.logout();
    },

    getUserData() {
        return currentUser;
    },

    async getAccessToken() {
        return await oidcClient.getAccessToken();
    },

    isAuthenticated() {
        return Boolean(currentUser);
    }
};

export default userStore;
