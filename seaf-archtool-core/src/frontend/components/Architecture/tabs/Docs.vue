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
      R.Piontik <r.piontik@mail.ru> - 2023
-->

<template>
  <v-card v-if="items?.length" class="card-item">
    <v-card-title>
      <v-icon start>mdi-file-document-outline</v-icon>
      <span class="title">Документы</span>
    </v-card-title>
    <v-card-text class="headline font-weight-bold">
      <tree v-bind:items="items" style="overflow-x: auto" />
    </v-card-text>
  </v-card>
</template>

<script>
  import Tree from '@front/components/Controls/Tree.vue';
  import query from '@front/manifest/query';

  export default {
    name: 'Docs',
    components: {
      Tree
    },
    props: {
      subject: { type: String, default: '' }
    },
    data() {
      return {
        items: []
      };
    },
    watch: {
      subject: {
        handler() {
          this.loadItems();
        },
        immediate: true
      }
    },
    methods: {
      async loadItems() {
        let counter = 0;
        const result = [];

        const expandItem = (expitem) => {
          let node = result;

          expitem.location.split('/').map((title, index, arr) => {
            let item = node.find((element) => element.title === title);

            if (!item) {
              node.push(
                item = {
                  title: title,
                  key: `${title}_${counter++}`,
                  items: []
                }
              );
            }

            if (arr.length - 1 === index) {
              item.link = expitem.link;
            }

            node = item.items;
          });
        };

        const docs = await query.expression(query.docsForSubject(this.subject)).evaluate() || [];
        docs.map((item) => expandItem(item));

        this.items = result;
      }
    }
  };
</script>

<style scoped>
  .card-item {
    width: 100%;
    margin-top: 12px;
  }

  .source-list-item {
    font-stretch: normal;
    font-size: 16px;
    font-weight: 300;
  }
</style>
