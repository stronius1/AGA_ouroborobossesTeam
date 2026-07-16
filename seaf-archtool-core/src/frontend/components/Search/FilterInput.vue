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
  <div>
    <v-menu
      v-if="field.type === 'rel'"
      v-model="relMenuOpen"
      v-bind:close-on-content-click="false"
      location="bottom"
      v-bind:offset="4"
      v-bind:max-height="300"
      content-class="rel-suggestions-menu">
      <template #activator="{ props }">
        <v-text-field
          v-bind="props"
          v-bind:model-value="value"
          density="compact"
          variant="outlined"
          hide-details
          clearable
          placeholder="Введите название для поиска…"
          v-on:update:modelValue="onRelInput">
          <template #append>
            <v-progress-circular
              v-if="relSuggestionsLoading"
              v-bind:indeterminate="true"
              v-bind:size="20"
              v-bind:width="2" />
          </template>
        </v-text-field>
      </template>
      <v-list density="compact">
        <v-list-item
          v-for="(item, idx) in relSuggestions"
          v-bind:key="idx"
          v-on:click="onRelSelect(item.value)">
          <v-list-item-title>{{ item.text }}</v-list-item-title>
        </v-list-item>
        <v-list-item v-if="relSuggestions.length === 0 && !relSuggestionsLoading" disabled>
          <v-list-item-title class="text-medium-emphasis">
            Введите минимум 1 символ
          </v-list-item-title>
        </v-list-item>
      </v-list>
    </v-menu>
    <component
      v-bind:is="inputComponent"
      v-else
      v-bind:model-value="value"
      v-bind="inputProps"
      v-on:update:modelValue="onInput" />
  </div>
</template>

<script>
  export default {
    name: 'FilterInput',
    props: {
      field: {
        type: Object,
        required: true
      },
      value: {
        type: [String, Number, Boolean],
        default: null
      },
      loadSuggestions: {
        type: Function,
        default: () => []
      }
    },
    emits: ['input'],
    data() {
      return {
        relSuggestions: [],
        relSuggestionsLoading: false,
        relSuggestDebounceTimer: null,
        relMenuOpen: false
      };
    },
    computed: {
      inputComponent() {
        if (this.field.type === 'number' || this.field.type === 'integer') {
          return 'v-text-field';
        }
        if (this.field.enumValues && this.field.enumValues.length) {
          return 'v-select';
        }
        return 'v-text-field';
      },
      inputProps() {
        const base = {
          density: 'compact',
          variant: 'outlined',
          'hide-details': true,
          clearable: true
        };
        if (this.field.type === 'number' || this.field.type === 'integer') {
          return {
            ...base,
            type: 'number',
            placeholder: this.field.title || this.field.key
          };
        }
        if (this.field.enumValues && this.field.enumValues.length) {
          return {
            ...base,
            items: this.field.enumValues,
            placeholder: this.field.title || this.field.key
          };
        }
        return {
          ...base,
          placeholder: this.field.title || this.field.key
        };
      }
    },
    methods: {
      onRelInput(value) {
        const val = this.normalizeInputValue(value);

        this.$emit('input', val);
        if (this.relSuggestDebounceTimer) {
          clearTimeout(this.relSuggestDebounceTimer);
        }

        const query = val != null ? String(val).trim() : '';
        if (query.length === 0) {
          this.relSuggestions = [];
          this.relMenuOpen = false;
          return;
        }

        this.relMenuOpen = true;
        this.relSuggestDebounceTimer = setTimeout(() => {
          this.loadRelSuggestions(query);
          this.relSuggestDebounceTimer = null;
        }, 400);
      },
      onRelSelect(selectedValue) {
        this.$emit('input', selectedValue);
        this.relMenuOpen = false;
      },
      normalizeInputValue(value) {
        if (value instanceof Event) {
          return value.target?.value ?? '';
        }

        if (value && typeof value === 'object' && 'target' in value) {
          return value.target?.value ?? '';
        }

        return value;
      },
      onInput(value) {
        this.$emit('input', this.normalizeInputValue(value));
      },
      async loadRelSuggestions(query) {
        const relTarget = this.field.relTarget;
        if (!relTarget || !query) {
          this.relSuggestions = [];
          return;
        }
        this.relSuggestions = [];
        this.relSuggestionsLoading = true;
        try {
          const data = await this.loadSuggestions(relTarget, query);
          this.relSuggestions = Array.isArray(data) ? data : [];
        } catch (e) {
          this.relSuggestions = [];
        } finally {
          this.relSuggestionsLoading = false;
        }
      }
    }
  };
</script>
