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
      R.Piontik <r.piontik@mail.ru> - 2025
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2023
      Vladislav Nefedov <clay.zenx@gmail.com>, Sber - 2024
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2025
-->

<template>
  <box
    v-bind:errors="errors"
    v-bind:path="path"
    v-on:doc-contextmenu="showContextMenu">
    <v-card>
      <v-card-title v-if="(source.dataset || []).length > 10 && !isPrintVersion">
        <v-text-field
          v-model="search"
          append-inner-icon="mdi-magnify"
          label="Поиск"
          single-line
          hide-details />
      </v-card-title>
      <v-data-table
        v-bind:mobile-breakpoint="0"
        v-bind:headers="tableHeaders"
        v-bind:items="items"
        v-bind:search="search"
        v-bind:items-per-page="isPrintVersion ? -1 : itemsPerPage"
        v-bind:items-per-page-options="itemsPerPageOptions"
        v-bind:multi-sort="true"
        v-bind:hide-default-footer="isPrintVersion"
        class="elevation-1 doc-table">
        <!-- eslint-disable vue/valid-v-slot -->
        <template #footer.prepend>
          <div class="doc-table__footer-left">
            <v-btn
              variant="text"
              color="primary"
              prepend-icon="mdi-export"
              v-on:click="handleExportToExcel">
              Экспорт в Excel
            </v-btn>
          </div>
        </template>
        <template #item="{ item }">
          <tr>
            <td
              v-for="(field, index) in rowFields(item.raw || item)"
              v-bind:key="index"
              v-bind:align="field.align">
              <template v-if="field.link">
                <d-c-link v-bind:href="field.link">{{ field.value }}</d-c-link>
              </template>
              <template v-else>{{ field.value }}</template>
            </td>
          </tr>
        </template>
        <template #no-data>
          <v-alert v-if="isReady" icon="mdi-warning">
            Данных нет :(
          </v-alert>
          <v-alert v-else>
            Тружусь...
          </v-alert>
        </template>
      </v-data-table>
    </v-card>
  </box>
</template>

<script>

  import DCLink from '@front/components/Controls/DCLink.vue';

  import DocMixin from './DocMixin';
  import exportToExcel from '@front/helpers/exportToExcel';

  export default {
    name: 'DocTable',
    components: {
      DCLink
    },
    mixins: [DocMixin],
    props: {
      document: { type: String, default: '' }
    },
    data() {
      return {
        search: '',
        isReady: false
      };
    },
    computed: {
      headers() {
        return this.profile?.headers || [];
      },
      tableHeaders() {
        return this.headers.map((column) => ({
          ...column,
          title: column.title || column.text,
          key: column.key ?? column.value
        }));
      },
      items() {
        const result = this.source.dataset || [];
        return Array.isArray(result) ? result : [result];
      },
      perPage() {
        return (this.profile || {})['per-page'];
      },
      isTemplate() {
        return true;
      },
      itemsPerPage() {
        return this.perPage || 5;
      },
      itemsPerPageOptions() {
        const lengthOptions = Array.from(
          new Set([5, 10, 15, 20, this.items.length])
        );

        return lengthOptions
          .sort((a, b) => a - b)
          .filter(v => v <= this.items.length);
      }
    },
    methods: {
      refresh() {
        this.sourceRefresh().finally(() => this.isReady = true);
      },
      handleExportToExcel() {
        exportToExcel(this.headers, this.source.dataset, this.document || this.id);
      },
      rowFields(row) {
        const result = this.headers.map((column) => {
          const columnKey = column.key ?? column.value;

          return {
            value: (row[columnKey] || '').toString().replace('\\n','\n'),
            link: column.link ? row[column.link] : undefined,
            align: column.align || 'left'
          };
        });
        return result;
      }
    }

  };
</script>

<style scoped>
table {
  max-width: 100%;
}
td {
  white-space: pre-wrap
}

.doc-table__footer-left {
  margin-right: auto;
}
</style>

<style>
.doc-table thead tr th {
  white-space: nowrap;
}
</style>
