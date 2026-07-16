<!--
  Copyright (C) 2026 Sber

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  restrictions under the License.

  Maintainers:
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber

  Contributors:
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2026
      Marat Niyazmatov, Sber - 2026
-->

<template>
  <div class="search-page">
    <!-- Строка поиска и переключатель сущностей -->
    <div class="search-header">
      <v-text-field
        v-model="searchQuery"
        variant="outlined"
        density="compact"
        clearable
        hide-details
        placeholder="Введите запрос для поиска..."
        prepend-inner-icon="mdi-magnify"
        class="search-input flex-grow-1"
        v-on:keyup.enter="performSearch" />
      <v-btn
        color="primary"
        class="ml-2"
        v-on:click="performSearch">
        Найти
      </v-btn>
      <v-btn
        v-bind:disabled="!(results?.length > 0)"
        color="primary"
        class="ml-2"
        v-on:click="csvExport">
        Экспорт CSV
      </v-btn>
    </div>

    <!-- Переключатель сущностей (типы объектов) -->
    <div class="entities-picker">
      <span>
        Поиск по сущностям:
        <span class="entity-indicator">{{ entities.find((ele) => ele.key === selectedEntityKey)?.title }}</span>
      </span>
      <button v-if="!entitiesLoading" class="entities-button" v-on:click="showEntities = !showEntities">{{ showEntities ? 'Скрыть' : 'Изменить' }}</button>
    </div>
    <div v-if="entities.length" v-bind:class="[{['entity-tabs--hidden']: !showEntities}, 'entity-tabs']">
      <div class="entity-chips">
        <v-chip
          v-for="ent in entities"
          v-bind:key="ent.key"
          v-bind:class="{ 'entity-chip--active': selectedEntityKey === ent.key }"
          v-bind:color="selectedEntityKey === ent.key ? 'primary' : undefined"
          v-bind:variant="selectedEntityKey !== ent.key ? 'outlined' : 'elevated'"
          size="x-small"
          style="margin: 0; cursor: pointer;"
          v-on:click="onEntitySelect(ent.key)">
          {{ ent.title }}
        </v-chip>
      </div>
    </div>

    <!-- Основной контент: результаты слева, фильтры справа -->
    <div class="search-content">
      <!-- Результаты поиска (левая колонка) -->
      <div class="results-column">
        <div class="results-panel">
          <div v-if="searchLoading" class="text-center pa-4">
            <v-progress-circular indeterminate color="primary" />
            <div class="mt-2">Загрузка...</div>
          </div>
          <div v-else-if="searchError" class="pa-3">
            <v-alert type="error" density="compact">{{ searchError }}</v-alert>
          </div>
          <div v-else-if="!selectedEntityKey" class="pa-4 text-center text-medium-emphasis">
            Выберите сущность для поиска
          </div>
          <div v-else-if="results.length === 0 && searchPerformed" class="pa-4 text-center text-medium-emphasis">
            Ничего не найдено
          </div>
          <div v-else-if="results.length > 0" class="results-list">
            <v-data-table
              v-bind:headers="tableHeaders"
              v-bind:items="results"
              v-bind:items-per-page="-1"
              item-value="itemKey"
              fixed-header
              height="100%"
              density="compact"
              hide-default-footer
              class="results-table">
              <template #[`item.company`]="{ item }">
                {{ item.company || '—' }}
              </template>
              <template #[`item.entityTitle`]="{ item }">
                {{ item.entityTitle || '—' }}
              </template>
              <template #[`item.title`]="{ item }">
                <a
                  v-if="item.card"
                  v-bind:href="getCardUrl(item.card)"
                  target="_blank"
                  rel="noopener"
                  class="result-link">{{ item.title || item._sfa_key || '—' }}</a>
                <span v-else>{{ item.title || item._sfa_key || '—' }}</span>
              </template>
              <template #[`item.description`]="{ item }">
                {{ item.description || '—' }}
              </template>
            </v-data-table>
          </div>
        </div>
      </div>

      <!-- Фильтры (правая колонка) -->
      <div class="filters-column">
        <div class="filters-panel">
          <div class="filters-header">Фильтры</div>
          <div v-if="!selectedEntityKey" class="pa-2 text-center text-medium-emphasis text-caption">
            Выберите сущность — появятся доступные фильтры
          </div>
          <div v-else-if="selectedEntityKey === '__all__'" class="pa-2 text-center text-medium-emphasis text-caption">
            В режиме «Все» поиск по словам в наименовании и описании
          </div>
          <div v-else-if="filterError" class="pa-2 text-center text-medium-emphasis text-caption">{{ filterError }}</div>
          <div v-else-if="filtersLoading" class="pa-2 text-center">
            <v-progress-circular indeterminate size="24" />
          </div>
          <div v-else-if="filterFields.length === 0" class="pa-2 text-center text-medium-emphasis text-caption">
            Нет фильтруемых полей
          </div>
          <div v-else class="filters-form">
            <div
              v-for="field in filterFields"
              v-bind:key="field.key"
              class="filter-field mb-2">
              <div class="filter-field-label">{{ field.title || field.key }}</div>
              <filter-input
                v-bind:field="field"
                v-bind:value="getFilterValue(field.key)"
                v-bind:load-suggestions="getFilterSuggestions"
                v-on:input="onFilterChange(field.key, $event)" />
            </div>
            <v-btn
              v-bind:disabled="!(activeFiltersCount > 0)"
              size="small"
              variant="text"
              color="primary"
              v-on:click="performSearch">
              Применить фильтры
            </v-btn>
            <v-btn
              v-bind:disabled="!outputIsFiltered"
              size="small"
              variant="text"
              color="primary"
              v-on:click="clearFilters">
              Сбросить фильтры
            </v-btn>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
  import { requestToBackend } from '@front/helpers/backend.api.helper';
  import datasets from '@front/helpers/datasets';
  import { getFiltersForEntity, getFilterValueSuggestions, getSearchEntitiesList, performInEntitySearch, performSearchAll } from '@global/search/search-perform.mjs';
  import { SearchDataProvider } from '@global/search/search-data.mjs';
  import FilterInput from './FilterInput.vue';
  import env from '@front/helpers/env';
  import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
  import { SEARCH_ALL_KEY } from '@global/search/constants.mjs';
  import { collectRelFields, parseRelTarget } from '@global/search/search-utils.mjs';
  import downloadHelper from '@front/helpers/download.js';

  const logger = getLoggerWithTag('search-component');

  export default {
    name: 'Search',
    components: {
      FilterInput
    },
    data() {
      return {
        showEntities: false,
        entities: [],
        hasCompanies: false,
        selectedEntityKey: null,
        filterFields: [],
        filterError: null,
        searchQuery: '',
        filters: {},
        results: [],
        searchLoading: false,
        searchError: null,
        searchPerformed: false,
        entitiesLoading: false,
        filtersLoading: false,
        outputIsFiltered: false,
        searchDataProvider: null
      };
    },
    computed: {
      activeFiltersCount() {
        return Object.keys(this.filters).filter(k => this.filters[k] != null && this.filters[k] !== '').length;
      },
      tableHeaders() {
        const headers = [
          { title: 'Ключ', key: '_sfa_key', sortable: true },
          { title: 'Тип объекта', key: 'entityTitle', sortable: true, width: '180px' },
          { title: 'Наименование', key: 'title', sortable: true },
          { title: 'Описание', key: 'description', sortable: true }
        ];
        if (this.hasCompanies) {
          headers.unshift({ title: 'Компания', key: 'company', sortable: true, width: '140px' });
        }
        return headers;
      }
    },
    watch: {
      selectedEntityKey(val) {
        if (val && val !== '__all__') {
          this.filters = {};
          this.loadFilterFields(val);
        } else {
          this.filterFields = [];
        }
      }
    },
    async mounted() {
      this.initSearchDataProvider();
      await this.loadEntities();
    },
    methods: {
      initSearchDataProvider() {
        if (env.isBackendMode || !this.manifest) {
          this.searchDataProvider = null;
          return;
        }
        this.searchDataProvider = new SearchDataProvider(this.manifest, (datasetId) =>
          datasets().releaseData(`/datasets/${datasetId}`)
        );
      },
      collectRelEntityIds(choice) {
        const fullSchema = this.manifest.schema ?? this.manifest;
        return collectRelFields(fullSchema, choice, this.manifest)
          .map(rel => parseRelTarget(rel.relTarget)?.entityId)
          .filter(Boolean);
      },
      async getFilterSuggestions(relTarget, query) {
        let data;
        try {
          if (env.isBackendMode) {
            data = await requestToBackend(
              `/seaf-core/api/core/storage/search/rel-suggestions?relTarget=${encodeURIComponent(relTarget)}&query=${encodeURIComponent(query)}`
            );
          } else {
            const parsed = parseRelTarget(relTarget);
            let entityData;
            if (parsed?.entityId && this.searchDataProvider) {
              entityData = await this.searchDataProvider.getEntityData(parsed.entityId);
            }
            data = getFilterValueSuggestions(this.manifest, relTarget, query.trim().toLowerCase(), entityData);
          }
        } catch (e) {
          logger.error(() => 'Error loading filter suggestions', { field: relTarget, query, error: e });
          return [];
        }
        return data;
      },
      async loadEntities() {
        this.entitiesLoading = true;
        try {
          const data = env.isBackendMode ? await requestToBackend('/seaf-core/api/core/storage/search/searchable-entities') : getSearchEntitiesList(this.manifest);
          const rawEntities = data?.entities ?? (Array.isArray(data) ? data : []);
          this.entities = Array.isArray(rawEntities) ? rawEntities : [];
          this.hasCompanies = Boolean(data?.hasCompanies);
          if (this.entities.length && !this.selectedEntityKey) {
            this.selectedEntityKey = this.entities[0].key;
          }
        } catch (e) {
          this.entities = [];
          this.hasCompanies = false;
          this.searchError = 'Не удалось загрузить список сущностей';
          logger.error(() => 'Failed to load the list of searchable entities', {
            error: e
          });
        } finally {
          this.entitiesLoading = false;
        }
      },
      async loadFilterFields(choice) {
        this.filtersLoading = true;
        this.filterError = null;
        try {
          let data;
          if (env.isBackendMode) {
            data = await requestToBackend(`/seaf-core/api/core/storage/search/entity-filters?choice=${encodeURIComponent(choice)}`);
          } else {
            const fullSchema = this.manifest.schema;
            const entitySchema = fullSchema?.properties?.[choice] ?? this.manifest.entities[choice]?.schema;
            if (!entitySchema) {
              throw new Error(`Schema for entity ${choice} not found`);
            }
            data = getFiltersForEntity(this.manifest, choice, fullSchema, entitySchema);
          }
          this.filterFields = Array.isArray(data) ? data : [];
          this.filters = {};
        } catch (e) {
          this.filterFields = [];
          this.filterError = 'Не удалось загрузить поля фильтров для сущности';
          logger.error('Error loading filter fields', {
            error: e,
            entity: choice
          });
        } finally {
          this.filtersLoading = false;
        }
      },
      onEntitySelect(key) {
        this.selectedEntityKey = key;
      },
      getFilterValue(fieldKey) {
        return this.filters[fieldKey];
      },
      onFilterChange(fieldKey, value) {
        this.filters = {
          ...this.filters,
          [fieldKey]: value
        };
      },
      clearFilters() {
        this.filters = {};
        this.performSearch();
      },
      buildFiltersArray() {
        const arr = [];
        this.filterFields.forEach(f => {
          const v = this.filters[f.key];
          if (v == null || v === '') return;
          let operator = 'eq';
          let ignoreCase = false;
          let value = v;
          if (f.type === 'string') {
            operator = 'contains';
            value = String(v);
            ignoreCase = true;
          } else if (f.type === 'rel') {
            operator = 'contains';
            value = String(v);
            ignoreCase = true;
          } else if (f.type === 'number' || f.type === 'integer') {
            value = Number(v);
          } else if (f.type === 'enum' || f.enumValues) {
            operator = 'eq';
            value = v;
          }
          arr.push({
            field: f.key,
            operator,
            value,
            ignoreCase
          });
        });
        return arr;
      },
      async performSearch() {
        if (!this.selectedEntityKey) return;
        this.searchLoading = true;
        this.searchError = null;
        this.searchPerformed = true;
        try {
          const filters = this.buildFiltersArray();
          const payload = {
            choice: this.selectedEntityKey,
            filters,
            searchQuery: this.searchQuery?.trim() || ''
          };
          let data;
          if (env.isBackendMode) {
            data = await requestToBackend('/seaf-core/api/core/storage/search/search-run', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(payload)
            });
          } else {
            const queryWords = payload.searchQuery.split(/\s+/).filter(Boolean);
            if (this.selectedEntityKey === SEARCH_ALL_KEY) {
              let entityDataMap;
              if (this.searchDataProvider) {
                const searchableIds = getSearchEntitiesList(this.manifest).entities
                  .map(e => e.key)
                  .filter(k => k !== SEARCH_ALL_KEY);
                entityDataMap = await this.searchDataProvider.getEntityDataMap(searchableIds);
              }
              data = performSearchAll(this.manifest, queryWords, entityDataMap);
            } else {
              const fullSchema = this.manifest.schema ?? this.manifest;
              const entitySchema = fullSchema?.properties?.[this.selectedEntityKey] ?? this.manifest.entities[this.selectedEntityKey]?.schema;
              let entityDataMap;
              let entityData;
              if (this.searchDataProvider) {
                const relEntityIds = this.collectRelEntityIds(this.selectedEntityKey);
                entityDataMap = await this.searchDataProvider.getEntityDataMap([
                  this.selectedEntityKey,
                  ...relEntityIds
                ]);
                entityData = entityDataMap[this.selectedEntityKey];
              }
              data = performInEntitySearch(
                this.manifest,
                fullSchema,
                entitySchema,
                payload.choice,
                payload.filters,
                queryWords,
                entityData,
                entityDataMap
              );
            }
          }
          if (Array.isArray(data)) {
            const results = data.map(item => {
              item.itemKey = this.getItemKey(item);
              return item;
            });
            this.results = results;
          } else {
            this.results = [];
          }
        } catch (e) {
          this.results = [];
          this.searchError = e?.message || 'Ошибка при выполнении поиска';
          logger.error(() => 'Error performing search', { error: e });
        } finally {
          this.searchLoading = false;
          this.outputIsFiltered = this.activeFiltersCount > 0;
        }
      },
      csvExport() {
        if (!this.results.length) return;
        const headers = this.tableHeaders.map(h => h.key);
        const input = this.results.map(item => {
          const output = [];
          headers.forEach(h => {
            output.push(item[h]);
          });
          return output;
        });
        const csvString = [
          headers.join(';'),
          ...input.map(row => {
            let output = [];
            for (const item of row) {
              if (item?.match(/[,;\r\n]/)) {
                output.push(`"${item}"`);
              } else {
                output.push(item);
              }
            }
            return output.join(';');
          })
        ].join('\n');
        const data = window.btoa(unescape(encodeURIComponent(csvString)));
        downloadHelper.download(`data:text/plain;base64,${data}`, 'search.csv');
      },
      getItemKey(item) {
        return `${item._sfa_entity || ''}_${item._sfa_key || ''}`;
      },
      getCardUrl(cardPath) {
        if (!cardPath) return '#';
        const base = window.location.origin || '';
        return cardPath.startsWith('/') ? base + cardPath : base + '/' + cardPath;
      }
    }
  };
</script>

<style scoped>
.search-page {
  display: flex;
  flex-direction: column;
  height: calc(100dvh - 67px);
  min-height: 600px;
  max-width: 1400px;
  margin: 0 auto;
  padding: 12px 16px;
}
.search-header {
  display: flex;
  align-items: center;
  height: auto;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.search-input {
  flex: 1;
  min-width: 300px;
  max-width: 600px;
}
.entities-picker {
  height: unset;
}
.entity-indicator {
  color: rgba(0, 117, 93);
}
.entities-button {
  margin: 0 15px;
  color: #5672fc;
  font-size: 15px;
  &:hover {
    color: #3b45f9;
  }
}
.entity-tabs {
  display: grid;
  grid-template-rows: 1fr;
  height: auto;
  margin-bottom: 8px;
  transition: grid-template-rows 0.5s ease;
}
.entity-tabs--hidden {
  grid-template-rows: 0fr;
}
.entity-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  overflow: hidden;
}
.entity-chips::v-deep .v-chip {
  height: 24px;
  font-size: 12px;
}
.entity-chip--active {
  font-weight: 600;
}
.search-content {
  display: flex;
  min-height: 300px;
  gap: 16px;
  align-items: stretch;
}
.results-column {
  flex-grow: 1;
  flex-basis: 0;
}
.filters-column {
  width: 280px;
  height: 100%;
}
@media (max-width: 960px) {
  .search-page {
    height: unset;
  }
  .search-content {
    flex-direction: column;
  }
  .result-column {
    width: 100%;
    height: auto;
  }
  .results-panel {
    height: unset;
  }
  .filters-column {
    order: -1;
    width: 100%;
    height: auto;
  }
}
.results-panel {
  height: 100%;
  background: var(--v-background-base, #fff);
  border: 1px solid rgba(0, 0, 0, 0.12);
  border-radius: 4px;
}
.results-panel .pa-8,
.results-panel .pa-4 {
  padding: 16px !important;
}
.results-list {
  position: relative;
  height: 100%;
  /* overflow: hidden; */
  border-radius: 0 0 4px 4px;
}
.filters-panel {
  display: flex;
  flex-direction: column;
  background: var(--v-background-base, #f5f5f5);
  border: 1px solid rgba(0, 0, 0, 0.12);
  border-radius: 4px;
  padding: 12px;
  height: 100%;
  overflow-y: auto;
}
.filters-header {
  font-weight: 600;
  margin-bottom: 12px;
  font-size: 14px;
}
.filter-field {
  margin-bottom: 12px;
}
.filter-field::v-deep input::placeholder {
  opacity: 0.5;
}
.filter-field-label {
  font-size: 12px;
  font-weight: 500;
  color: rgba(0, 0, 0, 0.87);
  margin-bottom: 4px;
}
.result-item {
  border-bottom: 1px solid rgba(0, 0, 0, 0.08);
  transition: background 0.2s;
}
.result-item:last-child {
  border-bottom: none;
}
.result-item:hover {
  background: rgba(0, 117, 94, 0.05);
}
.results-table {
  height: 100%;
}
.result-link {
  color: var(--v-primary-base, #00755e);
  text-decoration: none;
}
.result-link:hover {
  text-decoration: underline;
}
</style>
