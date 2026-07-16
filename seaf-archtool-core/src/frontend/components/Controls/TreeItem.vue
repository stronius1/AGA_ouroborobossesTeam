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
      R.Piontik <r.piontik@mail.ru> - 2021
-->

<template>
  <ul class="items">
    <li v-for="item in items" v-bind:key="item.key" v-bind:class="{'item': true, 'selected' : item.selected}">
      <v-icon v-if="item.items && item.items.length" class="expand-ico" v-on:click="onExpand(item)">
        <template v-if="expands[item.key]">mdi-chevron-down</template>
        <template v-else>mdi-chevron-right</template>
      </v-icon>
      <v-icon v-if="item.icon" class="item-ico" v-bind:style="item.iconStyle">
        {{ item.icon }}
      </v-icon>
      <router-link v-if="item.link" v-bind:to="item.link">
        {{ getTitleOfItem(item) }}
      </router-link>
      <template v-else>
        {{ getTitleOfItem(item) }}
      </template>
      <template v-if="item.items && expands[item.key]">
        <tree-item v-bind:expands="expands" v-bind:items="item.items" />
      </template>
    </li>
  </ul>
</template>

<script>

  const TreeItem = {
    name: 'TreeItem',
    mounted() {
      this.refreshExpand(this.items);
    },
    methods: {
      getTitleOfItem(item) {
        return item.count ? `${item.title} (${item.count})` : item.title;
      },
      refreshExpand(items) {
        items?.map((item) => {
          if (item.expand)
            this.expands[item.key] = item;
        });
      },
      onExpand(item) {
        if (this.expands[item.key]) {
          this.expands[item.key] = false;
        } else {
          this.expands[item.key] = item;
        }
      }
    },
    watch: {
      items(items) {
        this.refreshExpand(items);
      }
    },
    props: {
      items: Array,
      expands: Object
    },
    data() {
      return {};
    }
  };

  export default Object.assign(TreeItem, {
    components: {
      TreeItem
    }
  });

</script>

<style scoped>

  .items {
    list-style-type: none;
    padding-left: 28px;
    font-size: 16px;
  }

  .expand-ico {
    margin-left: -28px;
  }

  .item {
    padding-left: 4px;
    padding-right: 4px;
    width: fit-content;
  }

  .item.selected {
    background: rgb(52, 149, 219);
  }

  .item.selected * {
    color: #fff !important;
  }

</style>
