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
      Temnyakov Nikolay <temnjakovn@gmail.com>, Sber

  Contributors:
      Temnyakov Nikolay <temnjakovn@gmail.com>, Sber - 2026
-->

<template>
  <modal-upload
    v-bind:show="modal"
    v-bind:is-right-btn-loading="isLoading"
    v-on:close="isShowModal(false)"
    v-on:buttonRight="addFile"
    v-on:buttonLeft="isShowModal(false)">
    <template #header> Загрузить файлы</template>

    <template #body>
      <div class="upload-modal__container">
        <div class="upload-modal__header-block">
          <input-text
            class="upload-modal__description"
            v-bind:text="form.description"
            v-bind:max-length="200"
            v-on:inputText="addFileDescription">
            Краткое описание
          </input-text>
        </div>
      </div>

      <hr class="upload-modal__hr">

      <div v-if="!s3UrlConfigured" class="upload-modal__notice upload-modal__notice_warn">
        Не задан S3 service url. Загрузка файлов недоступна.
      </div>

      <div class="upload-modal__add-file">
        <upload-files
          v-bind:file-types="fileTypes"
          v-bind:max-size-mb="maxSizeMb"
          v-bind:max-files="maxFiles"
          v-bind:selected-files="form.files"
          v-on:uploadFile="uploads"
          v-on:fileError="onFileError" />
      </div>

      <div v-if="errorMessage" class="upload-modal__notice upload-modal__notice_error">
        {{ errorMessage }}
      </div>

      <div v-if="form.files.length" class="upload-modal__selected-files">
        <div class="upload-modal__section-title">Файлы к загрузке</div>
        <div v-for="file in form.files" v-bind:key="file.localId" class="upload-modal__selected-file">
          <div>
            <div class="upload-modal__file-name">{{ file.fileName }}</div>
            <div class="upload-modal__file-meta">{{ formatBytes(file.sizeBytes) }} · {{ file.mimeType }}</div>
          </div>
          <button class="upload-modal__remove-btn" v-on:click="removeFile(file.localId)">Удалить</button>
        </div>
      </div>

      <div v-if="batchInfo || uploadItems.length" class="upload-modal__statuses">
        <div class="upload-modal__section-title">Статус проверки</div>
        <div v-if="batchInfo" class="upload-modal__batch-summary">
          Batch: {{ batchInfo.batchId }} · {{ batchInfo.status }} · {{ batchInfo.fileCount }} файлов · {{ formatBytes(batchInfo.totalBytes) }}
        </div>

        <div v-for="item in uploadItems" v-bind:key="item.fileId || item.localId" class="upload-status-card">
          <div class="upload-status-card__header">
            <div>
              <div class="upload-status-card__title">{{ item.originalName || item.fileName }}</div>
              <div class="upload-status-card__subtitle">{{ item.fileId || 'local' }}</div>
            </div>
            <div class="upload-status-card__state" v-bind:class="statusClass(item.status)">
              {{ fileStatusLabel(item.status) || 'Ожидает' }}
            </div>
          </div>

          <div class="upload-status-card__meta">
            <span>{{ formatBytes(item.sizeBytes) }}</span>
            <span v-if="item.contentType">{{ item.contentType }}</span>
            <span>uploadValidated: {{ item.uploadValidated ? 'true' : 'false' }}</span>
          </div>

          <div v-if="validatorRows(item).length" class="upload-status-card__validators">
            <div v-for="validator in validatorRows(item)" v-bind:key="validator.key" class="upload-status-card__validator">
              <div>{{ validator.key }}: <strong>{{ validatorStatusLabel(validator.status) }}</strong></div>
              <div>
                попытка: {{ validator.attempt }}
                <span v-if="validator.nextAttemptAt"> · следующая: {{ validator.nextAttemptAt }}</span>
              </div>
              <div v-if="validator.lastError" class="upload-status-card__error">{{ validator.lastError }}</div>
            </div>
          </div>

          <div v-if="item.fileId" class="upload-status-card__actions">
            <button
              v-if="canRecheckUpload(item)"
              class="upload-status-card__action"
              v-bind:disabled="!!recheckingFileIds[item.fileId]"
              v-on:click="recheckUploadAction(item)">
              Перезапустить проверку загрузки
            </button>
            <button
              v-if="canRecheckDownload(item)"
              class="upload-status-card__action"
              v-bind:disabled="!!recheckingFileIds[item.fileId]"
              v-on:click="recheckDownloadAction(item)">
              Перезапустить проверку скачивания
            </button>
            <button
              class="upload-status-card__action"
              v-on:click="downloadAction(item)">
              Скачать
            </button>
          </div>
        </div>
      </div>
    </template>

    <template #button_left> Закрыть</template>
    <template #button_right> Загрузить</template>
  </modal-upload>
</template>

<script>
  import Modal from './Modal.vue';
  import InputText from './InputText.vue';
  import UploadFiles from './UploadFiles.vue';
  import env from '@front/helpers/env';
  import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
  import {ALLOWED_UPLOAD_FILE_TYPES} from './lib/helpers/allowedFileTypes';
  import {
    buildLegacyUploadResponse,
    getBatchStatus,
    getDownloadWaitingPageUrl,
    getFileStatus,
    recheckDownload,
    recheckUpload,
    requestDownload,
    uploadAsyncFiles
  } from './lib/helpers/asyncFile.api.js';
  import {
    isTerminalUploadStatus,
    isValidationActive,
    pollDelay
  } from './lib/helpers/fileStatus.utils.js';
  import { fileStatusLabel, validatorStatusLabel } from './lib/helpers/statusLabels.js';
  import { saveDownloadedFile } from './lib/helpers/fileDownload.js';
  import {
    canRecheckDownload as canRecheckDownloadPolicy,
    canRecheckUpload as canRecheckUploadPolicy
  } from './lib/helpers/recheckPolicy.js';

  const logger = getLoggerWithTag('f/c/U/ActionFileModal');

  const MAX_POLL_FAILURES = 5;
  const MAX_POLL_BACKOFF_MS = 5 * 60 * 1000;
  const PROMISE_STATUS_FULFILLED = 'fulfilled';
  const PROMISE_STATUS_REJECTED = 'rejected';

  export default {
    name: 'FileUploadModal',
    components: {
      'upload-files': UploadFiles,
      'input-text': InputText,
      'modal-upload': Modal
    },
    props: {
      modal: {
        type: Boolean
      },
      fileTypes: {
        type: Array,
        default: () => ALLOWED_UPLOAD_FILE_TYPES
      },
      maxSizeMb: {
        type: Number,
        default: 10
      },
      maxFiles: {
        type: Number,
        default: 10
      }
    },
    data() {
      return {
        form: {
          files: [],
          description: ''
        },
        isLoading: false,
        isError: false,
        errorMessage: '',
        uploadItems: [],
        batchInfo: null,
        pollTimer: null,
        pollFailureCount: 0,
        emittedFileIds: {},
        recheckingFileIds: {}
      };
    },
    computed: {
      s3UrlConfigured() {
        const url = String(env?.s3CloudUrl || '').trim();
        if (!url) {
          return false;
        }
        return /^https?:\/\/.+/i.test(url);
      }
    },
    beforeUnmount() {
      this.stopPolling();
    },
    methods: {
      resetState() {
        this.form.files = [];
        this.form.description = '';
        this.isLoading = false;
        this.isError = false;
        this.errorMessage = '';
        this.uploadItems = [];
        this.batchInfo = null;
        this.emittedFileIds = {};
        this.pollFailureCount = 0;
        this.stopPolling();
      },
      onFileError(err) {
        this.isError = true;
        logger.warn(() => `Ошибка выбора файла: code=${err?.code || 'UNKNOWN'}, fileName=${err?.fileName || ''}, message=${err?.message || ''}`);
      },

      formatUploadError(error) {
        const status = Number(error?.response?.status ?? error?.status ?? 0);
        const body = error?.response?.data ?? error?.data ?? '';
        const message = error?.message || (typeof body === 'string' ? body : '');

        if (status === 503 || /upstream connect error|connection (refused|failure)|ECONNREFUSED/i.test(message)) {
          return 'сервис загрузки временно недоступен, попробуйте позже';
        }
        if (status === 429) {
          return 'превышен лимит запросов — подождите и повторите';
        }
        if (status === 413) {
          return 'файл слишком большой для сервиса';
        }
        if (status === 401 || status === 403) {
          return 'нет доступа к сервису загрузки - проверьте авторизацию';
        }
        if (status >= 500 && status < 600) {
          return `сервис загрузки вернул ошибку (HTTP ${status})`;
        }
        if (status >= 400 && status < 500) {
          return `запрос отклонён (HTTP ${status}): ${message || 'причина не указана'}`;
        }
        return message || 'неизвестная ошибка';
      },

      isShowModal(bool) {
        this.$emit('modal', bool);
        if (!bool) this.resetState();
      },

      addFileDescription(description) {
        this.form.description = String(description || '').slice(0, 200);
      },

      uploads(files) {
        this.form.files = (files || []).map(file => ({
          ...file,
          localId: `${file.fileName}-${file.sizeBytes}-${Math.random().toString(16).slice(2)}`
        }));
        if (this.form.files.length) {
          this.isError = false;
          this.errorMessage = '';
        }
      },

      removeFile(localId) {
        this.form.files = this.form.files.filter(file => file.localId !== localId);
      },

      formatBytes(bytes = 0) {
        if (!bytes) return '0 B';
        const units = ['B', 'KB', 'MB', 'GB'];
        let size = bytes;
        let unitIndex = 0;

        while (size >= 1024 && unitIndex < units.length - 1) {
          size /= 1024;
          unitIndex += 1;
        }

        return `${size.toFixed(size >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
      },

      validatorRows(item) {
        return [
          ...Object.entries(item.uploadValidators || {}).map(([key, value]) => ({ key, ...value })),
          ...Object.entries(item.downloadValidators || {}).map(([key, value]) => ({ key: `download:${key}`, ...value }))
        ];
      },

      statusClass(status) {
        const normalized = String(status || '').toUpperCase();
        if (normalized.includes('REJECT') || normalized.includes('FAILED')) return 'upload-status-card__state_error';
        if (normalized.includes('VALID') || normalized.includes('READY') || normalized.includes('STORED')) return 'upload-status-card__state_ok';
        return 'upload-status-card__state_pending';
      },

      mergeUploadItems(items = []) {
        const map = new Map((this.uploadItems || []).map(item => [item.fileId || item.localId, item]));

        items.forEach(item => {
          const key = item.fileId || item.localId;
          if (!key) return;
          map.set(key, { ...(map.get(key) || {}), ...item });
        });

        this.uploadItems = Array.from(map.values());
      },

      emitAvailableUploads() {
        const available = this.uploadItems.filter(item => item?.fileId);

        if (!available.length) return;

        const notYetEmitted = available.filter(item => !this.emittedFileIds[item.fileId]);

        if (!notYetEmitted.length) return;

        logger.info(() =>
          `Отправляем ссылки в таблицу. total=${available.length}, new=${notYetEmitted.length}, ids=${notYetEmitted.map(item => item.fileId).join(', ')}`
        );

        this.$emit('upload', buildLegacyUploadResponse(available));
        this.$emit('upload-batch', notYetEmitted.map(item => buildLegacyUploadResponse(item)));

        const next = { ...(this.emittedFileIds || {}) };
        available.forEach(item => {
          next[item.fileId] = true;
        });
        this.emittedFileIds = next;
      },

      async addFile() {
        const MAX = this.maxSizeMb * 1024 * 1024;

        this.errorMessage = '';
        this.isError = false;

        if (!this.s3UrlConfigured) {
          this.isError = true;
          this.errorMessage = 'Не задан S3 service url. Загрузка файлов недоступна.';
          return;
        }

        if (!this.form.files.length) {
          this.isError = true;
          this.errorMessage = 'Не выбран ни один файл для загрузки';
          return;
        }

        if (this.form.files.length > this.maxFiles) {
          this.isError = true;
          this.errorMessage = `Слишком много файлов: выбрано ${this.form.files.length}, максимум ${this.maxFiles} за раз`;
          return;
        }

        const oversized = this.form.files.filter(file => file.sizeBytes > MAX);
        if (oversized.length) {
          this.isError = true;
          this.errorMessage = `Файлы превышают лимит ${this.maxSizeMb} МБ: ${oversized.map(f => f.fileName).join(', ')}`;
          return;
        }

        this.stopPolling();
        this.uploadItems = [];
        this.batchInfo = null;
        this.emittedFileIds = {};
        this.pollFailureCount = 0;

        try {
          this.isLoading = true;
          await this.$nextTick();
          await new Promise(resolve => requestAnimationFrame(resolve));

          const response = await uploadAsyncFiles(this.form.files, this.form.description);
          if (!response) {
            this.isLoading = false;
            return;
          }

          if (response.batchId) {
            this.batchInfo = response;

            const items = (response.files || []).map((file, index) => ({
              ...file,
              localId: file.fileId || this.form.files[index]?.localId || `batch-${index}`,
              fileName: file.originalName || file.fileName || this.form.files[index]?.fileName,
              originalName: file.originalName || file.fileName || this.form.files[index]?.fileName,
              sizeBytes: file.sizeBytes || this.form.files[index]?.sizeBytes,
              contentType: file.contentType || this.form.files[index]?.mimeType,
              status: file.status || response.status
            }));

            this.mergeUploadItems(items);
            this.emitAvailableUploads();
            this.startPolling();
          } else {
            const firstFile = this.form.files[0] || {};

            const singleItem = {
              fileId: response.fileId,
              localId: response.fileId || firstFile.localId,
              fileName: response.originalName || response.fileName || firstFile.fileName,
              originalName: response.originalName || response.fileName || firstFile.fileName,
              sizeBytes: response.sizeBytes || firstFile.sizeBytes,
              contentType: response.contentType || firstFile.mimeType,
              uploadValidated: response.uploadValidated,
              status: response.status
            };

            this.mergeUploadItems([singleItem]);
            this.emitAvailableUploads();
            this.startPolling();
          }
        } catch (e) {
          logger.error(() => 'Произошла ошибка при загрузке файлов', e);
          this.isError = true;
          this.errorMessage = `Не удалось загрузить файлы: ${this.formatUploadError(e)}`;
          this.isLoading = false;
        }
      },

      stopPolling() {
        if (this.pollTimer) {
          clearTimeout(this.pollTimer);
          this.pollTimer = null;
        }
      },

      startPolling() {
        this.stopPolling();
        this.pollFailureCount = 0;
        this.pollStatuses();
      },

      scheduleNextPoll() {
        this.stopPolling();
        const base = pollDelay();
        const delay = this.pollFailureCount > 0
          ? Math.min(base * Math.pow(2, this.pollFailureCount), MAX_POLL_BACKOFF_MS)
          : base;
        this.pollTimer = setTimeout(() => this.pollStatuses(), delay);
      },

      handlePollFailure(message) {
        this.pollFailureCount += 1;
        if (this.pollFailureCount >= MAX_POLL_FAILURES) {
          this.stopPolling();
          this.isLoading = false;
          this.isError = true;
          this.errorMessage = `Не удалось получить статусы файлов после ${MAX_POLL_FAILURES} попыток${message ? `: ${message}` : ''}. Попробуйте позже.`;
          return true;
        }
        return false;
      },

      async pollStatuses() {
        const hasBatchRequest = !!this.batchInfo?.batchId;

        try {
          const batchPromise = hasBatchRequest
            ? getBatchStatus(this.batchInfo.batchId)
            : Promise.resolve(this.batchInfo);

          const statusPromises = this.uploadItems.map(item =>
            item.fileId ? getFileStatus(item.fileId) : Promise.resolve(null)
          );

          const [batchResult, ...statusResults] = await Promise.allSettled([batchPromise, ...statusPromises]);

          if (batchResult.status === PROMISE_STATUS_FULFILLED) {
            this.batchInfo = batchResult.value;
          } else {
            logger.warn(() => `Не удалось получить статус батча ${this.batchInfo?.batchId || ''}: ${batchResult.reason?.message || batchResult.reason}`);
          }

          this.uploadItems = this.uploadItems.map((item, idx) => {
            const result = statusResults[idx];
            if (result?.status === PROMISE_STATUS_FULFILLED && result.value) {
              return { ...item, ...result.value };
            }
            if (result?.status === PROMISE_STATUS_REJECTED) {
              logger.warn(() => `Не удалось получить статус файла ${item.fileId}: ${result.reason?.message || result.reason}`);
            }
            return item;
          });

          this.emitAvailableUploads();

          const pollResults = [
            ...(hasBatchRequest ? [batchResult] : []),
            ...statusResults.filter((_, idx) => this.uploadItems[idx]?.fileId)
          ];
          const allRejected = pollResults.length > 0 && pollResults.every(r => r.status === PROMISE_STATUS_REJECTED);

          if (allRejected) {
            const firstError = pollResults.find(r => r.status === PROMISE_STATUS_REJECTED)?.reason;
            if (this.handlePollFailure(firstError?.message || String(firstError || ''))) return;
          } else {
            this.pollFailureCount = 0;
          }

          const shouldContinue = this.uploadItems.some(item => !isTerminalUploadStatus(item.status));
          if (shouldContinue) {
            this.scheduleNextPoll();
          } else {
            this.isLoading = false;
          }
        } catch (e) {
          logger.error(() => 'Не удалось получить статус файлов', e);
          if (this.handlePollFailure(e?.message || String(e))) return;
          this.scheduleNextPoll();
        }
      },

      canRecheckUpload(item) {
        return canRecheckUploadPolicy(item);
      },
      canRecheckDownload(item) {
        return canRecheckDownloadPolicy(item);
      },

      fileStatusLabel,
      validatorStatusLabel,

      markRecheckInProgress(fileId, inProgress) {
        const next = { ...this.recheckingFileIds };
        if (inProgress) {
          next[fileId] = true;
        } else {
          delete next[fileId];
        }
        this.recheckingFileIds = next;
      },

      async recheckUploadAction(item) {
        if (!item?.fileId) return;
        if (this.recheckingFileIds[item.fileId]) return;
        if (isValidationActive(item)) {
          logger.info(() => `recheck upload пропущен для ${item.fileId}: валидация уже активна`);
          return;
        }
        this.markRecheckInProgress(item.fileId, true);
        try {
          const response = await recheckUpload(item.fileId);
          logger.info(() => `recheck upload: ${response?.status || ''} ${response?.message || ''}`);
          this.startPolling();
        } catch (e) {
          logger.error(() => `Ошибка recheck upload для ${item.fileId}: ${e?.message || e}`);
        } finally {
          this.markRecheckInProgress(item.fileId, false);
        }
      },

      async recheckDownloadAction(item) {
        if (!item?.fileId) return;
        if (this.recheckingFileIds[item.fileId]) return;
        if (isValidationActive(item)) {
          logger.info(() => `recheck download пропущен для ${item.fileId}: валидация уже активна`);
          return;
        }
        this.markRecheckInProgress(item.fileId, true);
        try {
          logger.info(() => `Запуск recheck download для ${item.fileId}`);
          await recheckDownload(item.fileId);
          this.startPolling();
        } catch (e) {
          logger.error(() => `Не удалось запустить recheck download для ${item.fileId}`, e);
        } finally {
          this.markRecheckInProgress(item.fileId, false);
        }
      },

      async downloadAction(item) {
        try {
          if (!item?.fileId) return;

          const isOwner = item.owner === true || item.isOwner === true;

          if (!isOwner) {
            window.open(getDownloadWaitingPageUrl(item.fileId), '_blank', 'noopener,noreferrer');
            return;
          }

          const response = await requestDownload(item.fileId);
          await saveDownloadedFile(response, item.originalName || item.fileName || 'download.bin');
        } catch (e) {
          logger.error(() => `Ошибка скачивания файла ${item?.fileId || ''}: ${e?.message || e}`);
        }
      }
    }
  };
</script>

<style scoped>
.upload-modal__container {
  width: 100%;
}

.upload-modal__header-block {
  width: 100%;
  margin-bottom: 4px;
}

.upload-modal__description {
  display: block;
  width: 100%;
  max-width: 420px;
  position: relative;
}

.input.upload-modal__description {
  display: block;
  width: 100%;
  max-width: 420px;
}

.upload-modal__hr {
  width: calc(100% + 64px);
  height: 1px;
  border: none;
  background-color: #cfcfcf;
  margin: 24px -32px;
}

.upload-modal__add-file {
  width: 100%;
  margin-top: 8px;
}

.upload-modal__notice {
  max-width: 520px;
  margin: 12px auto;
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 20px;
}

.upload-modal__notice_warn {
  background: #fff4d6;
  color: #8a6a00;
  border: 1px solid #f1d67a;
}

.upload-modal__notice_error {
  background: #fde4e1;
  color: #b4372b;
  border: 1px solid #f3a8a0;
}

.upload-modal__selected-files {
  margin-top: 24px;
}

.upload-modal__section-title {
  margin: 0 0 16px;
  font-size: 18px;
  line-height: 24px;
  font-weight: 700;
  text-align: center;
}

.upload-modal__selected-file {
  max-width: 420px;
  margin: 0 auto 12px;
  padding: 16px 18px;
  border: 1px solid #d9e3dd;
  border-radius: 16px;
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.upload-modal__file-name {
  font-size: 16px;
  line-height: 22px;
  font-weight: 600;
  color: #2d2d2d;
  word-break: break-word;
}

.upload-modal__file-meta {
  margin-top: 6px;
  font-size: 14px;
  line-height: 20px;
  color: #6b7280;
}

.upload-modal__remove-btn {
  border: 1px solid #d9e3dd;
  border-radius: 12px;
  background: #f8fbf9;
  padding: 10px 14px;
  font-size: 14px;
  line-height: 18px;
  color: #2d2d2d;
  cursor: pointer;
  white-space: nowrap;
}

.upload-modal__remove-btn:hover {
  background: #eef6f1;
}

.upload-modal__statuses {
  margin-top: 28px;
}

.upload-modal__batch-summary {
  max-width: 520px;
  margin: 0 auto 16px auto;
  padding: 10px 14px;
  border-radius: 12px;
  background: #f5faf7;
  color: #4b5563;
  font-size: 14px;
  line-height: 20px;
}

.upload-status-card {
  max-width: 520px;
  margin: 0 auto 16px auto;
  padding: 16px;
  border: 1px solid #d9e3dd;
  border-radius: 16px;
  background: #fff;
}

.upload-status-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.upload-status-card__title {
  font-weight: 700;
  font-size: 16px;
  line-height: 22px;
  color: #2d2d2d;
  word-break: break-word;
}

.upload-status-card__subtitle {
  margin-top: 6px;
  font-size: 13px;
  line-height: 18px;
  color: #6b7280;
  word-break: break-all;
}

.upload-status-card__state {
  flex-shrink: 0;
  padding: 8px 12px;
  border-radius: 999px;
  font-size: 12px;
  line-height: 16px;
  font-weight: 700;
  white-space: nowrap;
}

.upload-status-card__state_pending {
  background: #fff6db;
  color: #8a6a00;
}

.upload-status-card__state_ok {
  background: #dff6e7;
  color: #156f3d;
}

.upload-status-card__state_error {
  background: #fde4e1;
  color: #b4372b;
}

.upload-status-card__meta {
  margin-top: 14px;
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
  font-size: 14px;
  line-height: 20px;
  color: #4b5563;
}

.upload-status-card__validators {
  margin-top: 14px;
}

.upload-status-card__validator {
  padding: 12px 14px;
  border-radius: 12px;
  background: #f7faf8;
  margin-bottom: 10px;
  font-size: 14px;
  line-height: 20px;
  color: #2d2d2d;
}

.upload-status-card__validator-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0;
}

.upload-status-card__error {
  margin-top: 8px;
  color: #c2410c;
  word-break: break-word;
}

.upload-status-card__actions {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  margin-top: 16px;
}

.upload-status-card__action {
  width: 100%;
  border: 1px solid #d9e3dd;
  border-radius: 12px;
  background: #fff;
  padding: 10px 14px;
  font-size: 14px;
  line-height: 18px;
  color: #2d2d2d;
  cursor: pointer;
  text-align: center;
}

.upload-status-card__action:hover:not(:disabled) {
  background: #f7faf8;
}

.upload-status-card__action:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
