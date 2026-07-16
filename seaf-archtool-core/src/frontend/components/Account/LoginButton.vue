<!--
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
      Nikolay Temnyakov <temnjakovn@gmail.com>, Sber - 2025
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
-->

<template>
  <v-btn class="login-button" v-on:click="login">
    Войти
  </v-btn>
</template>

<script>
  import userStore from '@front/store/userStore.js';

  export default {
    name: 'LoginButton',
    methods: {
      async login() {
        await userStore.login();
      }
    }
  };
</script>

<style scoped>
.login-button {
  border-radius: 6px;
  width: auto;
  min-width: 70px;
  height: 36px;
  padding: 0 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 14px;
  color: #fff;
  cursor: pointer;
  transition: background-color 0.25s ease, transform 0.2s ease;
}

.login-button:hover {
  background-color: #009e7a;
  transform: translateY(-1px);
}
</style>
