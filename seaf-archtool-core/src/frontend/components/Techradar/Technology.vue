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
      R.Piontik <r.piontik@mail.ru> - 2021
      R.Piontik <r.piontik@mail.ru> - 2023
-->


<template>
  <div>Radar/Technology</div>
  <!-- <v-container style="min-width: 100%">
    <h1>{{ technology }}</h1>
    <h3>{{ summary.title }}</h3>
    <div v-if="summary.aliases">Синонимы: {{ summary.aliases.join('; ') }}</div>
    <div v-if="summary.link">Сайт: <a v-bind:href="summary.link" target="_blank">{{ summary.link }}</a></div>
    <div class="summary-block">
      <div v-if="summary.components">Используется в компонентах:</div>
      <ul class="components">
        <li v-for="component in summary.components" v-bind:key="component.id" class="component">
          <router-link
            v-bind:to="`/architect/components/${component.id}`">
            {{ component.title }}
          </router-link>
        </li>
      </ul>
    </div>
    <div class="summary-block">
      <div v-if="summary.components">Встречается в контекстах:</div>
      <ul class="contexts">
        <li v-for="context in summary.contexts" v-bind:key="context.id" class="contexts">
          <router-link
            v-bind:to="`/architect/contexts/${context.id}`">
            {{ context.title }}
          </router-link>
        </li>
      </ul>
    </div>
  </v-container> -->
</template>

<script>
  // import jsonata from 'jsonata';

  // import query from '@front/manifest/query';

  // export default {
  //   components:{
  //   },
  //   props: {
  //     technology: { type: String, default: '' }
  //   },
  //   data() {
  //     return {
  //     };
  //   },
  //   computed: {
  //     summary() {
  //       return (jsonata(query.summaryForTechnology(this.technology))
  //         .evaluate() || []);
  //     }
  //   }
  // };
</script>

<style scoped>
.summary-block {
  margin-top: 16px;
}
</style>
