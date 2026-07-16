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
      Artyom Prilip <artyom.prilip@gmail.com>, Sber - 2026
-->

<template>
  <v-card width="250" class="pa-3">
    <h3>
      <template v-if="user?.name || user?.surname">
        {{ [user.name, user.surname].filter(Boolean).join(' ') }}
      </template>
      <template v-else>
        <div style="font-size: 12px;">ID: {{ user?.userId }}</div>
      </template>
    </h3>
    <div v-if="rolesList.length">
      <p><strong>Роли:</strong></p>
      <ul class="roles-list">
        <li v-for="role in rolesList" v-bind:key="role">{{ role }}</li>
      </ul>
    </div>
    <v-divider class="my-2" />
    <v-btn
      block
      variant="text"
      size="small"
      color="primary"
      class="d-flex align-center justify-start py-1 px-2"
      style="font-size: 12px;"
      v-on:click="logout">
      <v-icon start size="16" class="mr-1">mdi-exit-to-app</v-icon>
      Выход
    </v-btn>
  </v-card>
</template>
<script>

  import userStore from '@front/store/userStore.js';

  export default {
    props: {
      // eslint-disable-next-line vue/require-default-prop
      user: Object
    },
    computed: {
      rolesList() {
        const roles = this.user?.roles || [];

        return roles
          .map((r) => (typeof r === 'string' ? r : r?.role)?.trim())
          .filter(Boolean);
      }
    },
    methods: {
      async logout() {
        await userStore.logout();
      }
    }
  };
</script>

<style scoped>
  h3 {
    margin-bottom: 0.5rem;
  }

  h4 {
    margin-bottom: 0.5rem;
    color: #0000008a;
  }

  button {
    cursor: pointer;
    background-color: transparent;
    border: none;
    display: flex;
    align-items: center;
    color: #0000008a;
  }
</style>
