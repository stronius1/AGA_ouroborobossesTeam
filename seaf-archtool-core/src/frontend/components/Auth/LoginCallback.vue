<!--
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
-->

<template>
  <div class="text-center mt-10">
    <h2>Авторизация...</h2>
  </div>
</template>

<script>
  import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
  import userStore from '@front/store/userStore.js';

  const logger = getLoggerWithTag('f/c/LoginCallback');

  export default {
    name: 'LoginCallback',
    async mounted() {
      try {
        // проверяем есть ли параметры OIDC в URL
        const hasOidcParams = window.location.hash.includes('state=') && window.location.hash.includes('session_state=');

        if (hasOidcParams) {
          await userStore.signinCallback();
          logger.debug(() => 'OIDC login successful');
          // очищаем URL, чтобы повторный ререндер не вызывал signinCallback
          window.history.replaceState({}, document.title, '/');
          // }
        } else {
          logger.debug(() => 'Нет OIDC параметров — signinCallback пропущен');
        }
      } catch (err) {
        logger.error(() => 'Ошибка LoginCallback.mounted signinCallback', err);
      }
    }
  };
</script>
