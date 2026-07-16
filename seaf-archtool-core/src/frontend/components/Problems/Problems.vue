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
      R.Piontik <r.piontik@mail.ru> - 2021
      R.Piontik <r.piontik@mail.ru> - 2022
      Rostislav Kabalin <kabalin2009@yandex.ru> - 2022
      Artyom Prilip <artyom.prilip@gmail.com>, Sber - 2026
-->

<template>
  <v-container fluid>
    <v-row>
      <v-col cols="12" md="5" class="d-flex">
        <validators v-bind:subject="subject" />
      </v-col>
      <v-col cols="12" md="7" class="d-flex">
        <problem-blank v-if="subject" v-bind:subject="subject" />
      </v-col>
    </v-row>
  </v-container>
</template>

<script>
  import Validators from './tabs/Validators.vue';
  import ProblemBlank from './tabs/ProblemBlank.vue';

  export default {
    name: 'Problems',
    components: {
      Validators,
      ProblemBlank
    },
    props: {
      subject: { type: String, default: '' }
    },
    data() {
      return {
      };
    },
    methods: {
      onGoto(route) {
        window.$PAPI.goto(route);
      }
    }
  };
</script>
