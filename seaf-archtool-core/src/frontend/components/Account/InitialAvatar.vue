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
  <v-menu content-class="user-profile-card" location="bottom">
    <template #activator="{ props }">
      <v-avatar v-bind="props" v-bind:color="avatarColor">
        <template v-if="user?.initials">
          {{ user.initials }}
        </template>
        <template v-else>
          <v-icon color="#00755D">mdi-account</v-icon>
        </template>
      </v-avatar>
    </template>
    <user-profile v-bind:user="user" />
  </v-menu>
</template>

<script>
  import UserProfile from '@front/components/Account/UserProfile.vue';
  import userStore from '@front/store/userStore.js';

  export default {
    name: 'InitialAvatar',
    components: {
      'user-profile': UserProfile
    },
    props: {
      avatarColor: { type: String, default: '#FFFFFF' }
    },
    computed: {
      user() {
        return userStore.getUserData();
      }
    }
  };
</script>

<style scoped>
.v-avatar {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
  font-size: 18px;
  color: rgb(0, 117, 93);
}
</style>
