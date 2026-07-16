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
  limitations under the License.

  Maintainers:
      Temnyakov Nikolay <temnjakovn@gmail.com>, Sber - 2026
-->

<template>
  <div class="file-status-row" v-bind:class="itemClasses">
    <div class="file-status-row__summary" v-on:click="toggleExpanded">
      <div class="file-status-row__summary-left">
        <v-icon size="small" class="file-status-row__caret">
          {{ expanded ? 'mdi-menu-down' : 'mdi-menu-right' }}
        </v-icon>
        <span class="file-status-row__name">{{ file.originalName || file.fileId }}</span>
        <span
          v-if="highlightLabel"
          class="file-status-row__event-badge"
          v-bind:class="eventBadgeClass">
          {{ highlightLabel }}
        </span>
      </div>
      <div class="file-status-row__summary-right">
        <span class="file-status-row__size">{{ file.__formattedSize }}</span>
        <span class="file-status-row__status" v-bind:class="file.__statusClass">{{ fileStatusLabel(file.status) }}</span>
      </div>
    </div>

    <div v-if="expanded" class="file-status-row__details">
      <div v-if="file.contentType || file.__sourceLine || file.__sourceDetails" class="file-status-row__meta">
        <span v-if="file.contentType">{{ file.contentType }}</span>
        <div v-if="file.__sourceLine" class="file-status-row__source">{{ file.__sourceLine }}</div>
        <div v-if="file.__sourceDetails" class="file-status-row__source file-status-row__source_secondary">
          <template v-if="file.__sourceLink">
            <a
              class="file-status-row__link"
              v-bind:href="file.__sourceLink"
              v-bind:target="file.__sourceLinkTarget"
              rel="noopener noreferrer">
              {{ file.__sourceDetails }}
            </a>
          </template>
          <template v-else>
            {{ file.__sourceDetails }}
          </template>
        </div>
      </div>

      <div v-if="file.__formattedCreatedAt" class="file-status-row__meta">
        Создан: {{ file.__formattedCreatedAt }}
      </div>

      <div class="file-status-row__meta file-status-row__meta_main">
        Проверка загрузки: {{ file.uploadValidated ? 'пройдена' : 'не пройдена' }}
        <span v-if="file.__formattedDownloadValidatedAt">
          · Проверка скачивания: {{ file.__formattedDownloadValidatedAt }}
        </span>
      </div>

      <div
        v-if="file.__isRejected"
        class="file-status-row__result file-status-row__result_error">
        Итог: файл отклонён
      </div>

      <div v-if="file.__validatorRows.length" class="file-status-row__validators">
        <div
          v-for="validator in file.__validatorRows"
          v-bind:key="validator.key"
          class="file-status-row__validator"
          v-bind:class="validator.__class">
          <span class="file-status-row__validator-name">{{ validator.key }}</span>
          <strong>{{ validatorStatusLabel(validator.status) }}</strong>
          <span v-if="validator.attempt !== null">
            · попытка {{ validator.attempt }}
          </span>
          <span v-if="validator.lastError"> · {{ validator.lastError }}</span>
        </div>
      </div>

      <div class="file-status-row__actions">
        <v-btn
          size="small"
          variant="outlined"
          color="primary"
          v-on:click.stop="$emit('download', file)">
          Скачать
        </v-btn>
        <v-btn
          v-if="canRecheckUpload_"
          size="small"
          variant="outlined"
          color="orange"
          v-bind:disabled="recheckInProgress"
          v-bind:loading="recheckInProgress"
          v-on:click.stop="$emit('recheck-upload', file)">
          Перезапустить проверку загрузки
        </v-btn>
        <v-btn
          v-if="canRecheckDownload_"
          size="small"
          variant="outlined"
          color="orange"
          v-bind:disabled="recheckInProgress"
          v-bind:loading="recheckInProgress"
          v-on:click.stop="$emit('recheck-download', file)">
          Перезапустить проверку скачивания
        </v-btn>
      </div>
    </div>
  </div>
</template>

<script>
  import { HIGHLIGHT_TYPE } from '@front/components/Account/fileHighlight.js';
  import {
    fileStatusLabel,
    validatorStatusLabel,
    highlightLabelRu
  } from '@front/components/Uploader/lib/helpers/statusLabels.js';
  import {
    canRecheckDownload,
    canRecheckUpload
  } from '@front/components/Uploader/lib/helpers/recheckPolicy.js';

  export default {
    name: 'FileStatusRow',
    props: {
      file: { type: Object, required: true },
      highlightType: { type: String, default: null },
      recheckInProgress: { type: Boolean, default: false }
    },
    emits: ['download', 'recheck-upload', 'recheck-download'],
    data() {
      return {
        expanded: !!this.file.__hasError
      };
    },
    computed: {
      itemClasses() {
        return {
          'file-status-row_new': this.highlightType === HIGHLIGHT_TYPE.NEW,
          'file-status-row_updated': this.highlightType === HIGHLIGHT_TYPE.UPDATED,
          'file-status-row_error': this.highlightType === HIGHLIGHT_TYPE.ERROR || this.file.__hasError
        };
      },
      highlightLabel() {
        return highlightLabelRu(this.highlightType);
      },
      eventBadgeClass() {
        return {
          'file-status-row__event-badge_new': this.highlightType === HIGHLIGHT_TYPE.NEW,
          'file-status-row__event-badge_updated': this.highlightType === HIGHLIGHT_TYPE.UPDATED,
          'file-status-row__event-badge_error': this.highlightType === HIGHLIGHT_TYPE.ERROR
        };
      },
      canRecheckUpload_() {
        return canRecheckUpload(this.file);
      },
      canRecheckDownload_() {
        return canRecheckDownload(this.file);
      }
    },
    methods: {
      toggleExpanded() {
        this.expanded = !this.expanded;
      },
      fileStatusLabel,
      validatorStatusLabel
    }
  };
</script>

<style scoped>
.file-status-row {
  border: 1px solid #d9e3dd;
  border-radius: 12px;
  padding: 8px 12px;
  margin-bottom: 8px;
  background: #fff;
  transition: background-color .4s ease, border-color .4s ease, box-shadow .4s ease;
  contain: layout style;
}

.file-status-row__summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  cursor: pointer;
  user-select: none;
}

.file-status-row__summary-left {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
}

.file-status-row__summary-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.file-status-row__caret {
  flex-shrink: 0;
}

.file-status-row__size {
  font-size: 12px;
  color: #586069;
  white-space: nowrap;
}

.file-status-row__details {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #eef2f0;
}

.file-status-row_new {
  background: #eefaf1;
  border-color: #9ad1ad;
}

.file-status-row_updated {
  background: #fff9e8;
  border-color: #e6c35c;
}

.file-status-row_error {
  border-color: #d77c75;
}

.file-status-row__row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.file-status-row__header-left {
  min-width: 0;
  flex: 1;
}

.file-status-row__name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.file-status-row__name {
  font-weight: 600;
  word-break: break-word;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

.file-status-row__meta {
  font-size: 12px;
  color: #586069;
  margin-top: 6px;
}

.file-status-row__meta_main {
  margin-top: 10px;
}

.file-status-row__source {
  font-size: 12px;
  margin-top: 6px;
  color: #1b5e20;
}

.file-status-row__source_secondary {
  color: #6b7280;
  word-break: break-all;
}

.file-status-row__result {
  margin-top: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
}

.file-status-row__result_error {
  background: #fde4e1;
  color: #b4372b;
}

.file-status-row__validators {
  margin-top: 10px;
  display: grid;
  gap: 8px;
}

.file-status-row__validator {
  font-size: 12px;
  border-radius: 8px;
  padding: 8px 10px;
  word-break: break-word;
}

.file-status-row__validator_ok {
  background: #e7f6eb;
  color: #156f3d;
}

.file-status-row__validator_pending {
  background: #fff6db;
  color: #8a6a00;
}

.file-status-row__validator_error {
  background: #fde4e1;
  color: #b4372b;
}

.file-status-row__validator_muted {
  background: #f1f3f5;
  color: #6b7280;
}

.file-status-row__validator-name {
  text-transform: none;
}

.file-status-row__validator-name::after {
  content: ": ";
}

.file-status-row__actions {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
}

.file-status-row__actions .v-btn {
  width: 100%;
  margin: 0;
}

.file-status-row__status {
  padding: 4px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.file-status-row__status_pending {
  background: #fff6db;
  color: #8a6a00;
}

.file-status-row__status_ok {
  background: #dff6e7;
  color: #156f3d;
}

.file-status-row__status_error {
  background: #fde4e1;
  color: #b4372b;
}

.file-status-row__event-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 999px;
}

.file-status-row__event-badge_new {
  background: #dff6e7;
  color: #156f3d;
}

.file-status-row__event-badge_updated {
  background: #fff6db;
  color: #8a6a00;
}

.file-status-row__event-badge_error {
  background: #fde4e1;
  color: #b4372b;
}

.file-status-row__link {
  color: inherit;
  text-decoration: underline;
}

.file-status-row__link:hover {
  opacity: 0.85;
}
</style>
