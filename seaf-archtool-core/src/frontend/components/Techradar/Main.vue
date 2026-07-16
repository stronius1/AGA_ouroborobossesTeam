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
      R.Piontik <r.piontik@mail.ru> - 2023
      Rostislav Kabalin <kabalin2009@yandex.ru> - 2022
-->

<template>
  <div>TechRadar migration is in progress ...</div>
  <!-- <v-container grid-list-xl fluid>
    <v-layout wrap>
      <v-flex xs12 md9 d-flex>
        <radar v-model="technologies" v-bind:section="section" />
      </v-flex>
      <v-flex xs12 md3 d-flex>
        <v-layout wrap>
          <v-flex v-for="(legend, key) in legends" v-bind:key="key" xs4 md12 d-flex>
            <ul class="sections">
              <li class="section-header">
                {{ legend.section.title }}
                <ul class="section-record">
                  <li v-for="record in legend.items" v-bind:key="record.index">
                    <router-link
                      v-bind:to="`/technology/${record.item.key}`">
                      {{ record.index ? `${record.index}: `: '' }} {{ record.item.key }}
                    </router-link>
                  </li>
                </ul>
              </li>
            </ul>
          </v-flex>
        </v-layout>
      </v-flex>
    </v-layout>
  </v-container> -->
</template>

<script>
  // import Radar from './Radar';

  // export default {
  //   components:{
  //     Radar
  //   },
  //   props: {
  //     section: { type: String, default: '' }
  //   },
  //   data() {
  //     return {
  //       technologies: []
  //     };
  //   },
  //   computed: {
  //     legends() {
  //       const result = {};
  //       this.technologies.map((record) => {
  //         const section = record.item.section;
  //         !result[section.key] && (result[section.key] = {section, items: []});
  //         result[section.key].items.push(record);
  //       });
  //       return result;
  //     }
  //   }
  // };
</script>

<style scoped>
ul .section-header {
  margin-bottom: 16px;
}
ul.sections {
  list-style-type: none;
  font-weight: 700;
  font-size: 12px;
}
ul.sections li {
  margin-left: 0px;
}
ul.section-record {
  font-weight: 300;
  list-style-type: none;
  margin-top: 6px;
}
</style>
