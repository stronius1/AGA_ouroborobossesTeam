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
      Rostislav Kabalin <kabalin2009@yandex.ru> - 2022
      R.Piontik <r.piontik@mail.ru> - 2022
-->

<template>
  <div style="width: 160px; height: 32px; left: 50%; top: 50%; position: absolute; margin-left: -80px; margin-top: -16px; text-align:center;">
    <template v-if="isLoading">
      Вжуууух...
    </template>
    <template v-else>
      Упс... здесь пусто :(
    </template>
  </div>
</template>

<script>
  export default {
    name: 'Empty',
    data() {
      return {};
    },
    computed: {
      isLoading() {
        return this.$store.state.isReloading;
      }
    }
  };
</script>
