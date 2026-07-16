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
  <div
    class="upload-files"
    v-bind:class="{ 'upload-files_dragover': isDragOver }"
    v-on:dragover.prevent="onDragOver"
    v-on:dragleave.prevent="onDragLeave"
    v-on:drop.prevent="onDrop">
    <div class="upload-files__main">
      <button-upload class="upload-files__btn" v-bind:color="'outlined'" v-on:click="uploadFiles">
        <template #button_text>Выбрать файлы</template>
        <template #button_icon><icon-add-file /></template>
      </button-upload>

      <input
        id="inputFile"
        ref="inputAddFile"
        type="file"
        name="file"
        v-bind:accept="acceptTypeString"
        class="upload-files__input"
        v-bind:multiple="true"
        v-on:change="onInputChange">

      <transition name="fade" mode="out-in">
        <span v-if="fileDescription" class="upload-files__description">
          {{ fileDescription }}
        </span>
        <span v-else class="upload-files__description">
          <slot name="description">
            выберите до {{ maxFiles }} файлов, каждый до {{ maxSizeMb }} МБ
          </slot>
        </span>
      </transition>
    </div>

    <transition name="fade" mode="out-in">
      <div v-if="errorText" class="upload-files__error-block">
        <span class="upload-files__error">{{ errorText }}</span>
        <details v-if="errorCode === 'FILE_EXTENSION_NOT_ALLOWED'" class="upload-files__error-details">
          <summary>Показать разрешённые типы</summary>
          <div class="upload-files__error-types">{{ normalizedFileTypes.join(', ') }}</div>
        </details>
      </div>
    </transition>
  </div>
</template>

<script>
  import Button from './buttons/Button.vue';
  import IconAddFile from './icons/IconAddFile.vue';
  import env, { Plugins } from '@front/helpers/env';
  import { ALLOWED_UPLOAD_FILE_TYPES, normalizeFileTypes } from './lib/helpers/allowedFileTypes';
  import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

  const logger = getLoggerWithTag('f/c/UploadFiles');

  export default {
    name: 'UploadFiles',

    components: {
      'button-upload': Button,
      'icon-add-file': IconAddFile
    },

    props: {
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
      },
      selectedFiles: {
        type: Array,
        default: () => []
      }
    },

    data() {
      return {
        errorText: '',
        errorCode: null,
        isDragOver: false
      };
    },

    computed: {
      maxBytes() {
        return this.maxSizeMb * 1024 * 1024;
      },

      normalizedFileTypes() {
        return normalizeFileTypes(this.fileTypes);
      },

      acceptTypeString() {
        return (this.fileTypes || []).join(',');
      },

      fileDescription() {
        const files = this.selectedFiles || [];
        if (!files.length) return '';
        if (files.length === 1) {
          return files[0]?.fileName || files[0]?.name || '';
        }
        return `Выбрано файлов: ${files.length}`;
      }
    },

    methods: {
      async uploadFiles() {
        this.clearError();

        if (env.isPlugin(Plugins.idea)) {
          let items;
          try {
            items = await window.$PAPI.s3UploadRequest();
          } catch (exception) {
            const message = String(exception?.message || exception);
            logger.error(() => `s3UploadRequest failed: ${message}`);
            this.setError('UPLOAD_PAYLOAD_ERROR', message);
            this.$emit('fileError', {code: 'UPLOAD_PAYLOAD_ERROR', message});
            return;
          }
          if (!items) return;
          await this.upload(items);
          return;
        }

        this.$refs.inputAddFile && this.$refs.inputAddFile.click();
      },

      onDragOver() {
        this.isDragOver = true;
      },

      onDragLeave() {
        this.isDragOver = false;
      },

      resetNativeInput() {
        if (this.$refs.inputAddFile) {
          this.$refs.inputAddFile.value = '';
        }
      },

      extOf(fileName) {
        const name = String(fileName || '');
        const idx = name.lastIndexOf('.');
        return idx >= 0 ? name.slice(idx).toLowerCase() : '';
      },

      validateExtension(fileName) {
        if (!this.normalizedFileTypes.length) return true;

        const ext = this.extOf(fileName);
        const ok = this.normalizedFileTypes.includes(ext);

        if (!ok) {
          const message = `Пропущен файл "${fileName}" — тип не поддерживается`;
          this.setError('FILE_EXTENSION_NOT_ALLOWED', message);
          this.$emit('fileError', {code: 'FILE_EXTENSION_NOT_ALLOWED', message, allowed: this.normalizedFileTypes, actual: ext || null, fileName});
        }

        return ok;
      },

      validateSize(sizeBytes, fileName) {
        if (sizeBytes > this.maxBytes) {
          const message = `Файл "${fileName}" слишком большой (${this.formatMb(sizeBytes)} МБ). Максимум ${this.maxSizeMb} МБ`;
          this.setError('FILE_TOO_LARGE', message);
          this.$emit('fileError', {code: 'FILE_TOO_LARGE', message, maxBytes: this.maxBytes, sizeBytes, fileName});
          return false;
        }
        return true;
      },

      validateNotEmpty(sizeBytes, fileName) {
        if (sizeBytes > 0) return true;
        const message = `Файл "${fileName}" пуст — отправка невозможна`;
        this.setError('FILE_EMPTY', message);
        this.$emit('fileError', {
          code: 'FILE_EMPTY',
          message,
          fileName
        });
        return false;
      },
      checkCountLimit(incomingCount) {
        const alreadySelected = (this.selectedFiles || []).length;
        const capacity = Math.max(0, this.maxFiles - alreadySelected);

        if (incomingCount <= capacity) {
          return incomingCount;
        }

        const message = `Слишком много файлов: выбрано ${alreadySelected + incomingCount}, максимум ${this.maxFiles} за раз. Первые ${capacity} будут приняты, остальные проигнорированы.`;
        this.setError('TOO_MANY_FILES', message);
        this.$emit('fileError', {code: 'TOO_MANY_FILES', message, maxFiles: this.maxFiles, alreadySelected, incomingCount});
        return capacity;
      },

      setError(code, message) {
        this.errorText = message;
        this.errorCode = code;
      },

      clearError() {
        this.errorText = '';
        this.errorCode = null;
      },
      finalizeValidation({ countLimitSkipped, validationSkipped, totalInput }) {
        const totalSkipped = countLimitSkipped + validationSkipped.length;

        if (totalSkipped === 0 && totalInput > 0) {
          this.clearError();
          return;
        }

        const needAggregate = validationSkipped.length > 1 || (countLimitSkipped > 0 && validationSkipped.length > 0);

        if (needAggregate) {
          const parts = [];
          if (countLimitSkipped > 0) {
            parts.push(`превышен лимит файлов — ${countLimitSkipped}`);
          }
          if (validationSkipped.length > 0) {
            const preview = validationSkipped.slice(0, 3).join(', ');
            const rest = validationSkipped.length > 3 ? `, ещё ${validationSkipped.length - 3}` : '';
            parts.push(`не прошли валидацию — ${validationSkipped.length} (${preview}${rest})`);
          }
          this.setError('FILES_SKIPPED', `Пропущено файлов: ${totalSkipped}. Причины: ${parts.join('; ')}`);
        }
      },

      formatMb(bytes) {
        return (bytes / (1024 * 1024)).toFixed(1);
      },

      async normalizePluginPayload(rawFile) {
        const { data, fileName, contentType } = rawFile;
        const binaryString = atob(data);
        const len = binaryString.length;
        const uint8Array1 = new Uint8Array(len);
        const chunkSize = 0x40000;

        for (let offset = 0; offset < len; offset += chunkSize) {
          const end = Math.min(offset + chunkSize, len);
          for (let i = offset; i < end; i++) {
            uint8Array1[i] = binaryString.charCodeAt(i);
          }
          if (end < len) {
            await new Promise(resolve => setTimeout(resolve, 0));
          }
        }

        return {
          uint8Array1,
          fileName,
          sizeBytes: len,
          mimeType: contentType || 'application/octet-stream'
        };
      },

      async upload(payload) {
        this.clearError();
        await this.$nextTick();
        await new Promise(resolve => requestAnimationFrame(resolve));

        try {
          const items = Array.isArray(payload) ? payload : [payload];
          const acceptCount = this.checkCountLimit(items.length);
          const limited = items.slice(0, acceptCount);
          const countLimitSkipped = items.length - acceptCount;

          const validFiles = [];
          const validationSkipped = [];
          for (const rawFile of limited) {
            if (!rawFile?.fileName || !rawFile?.data) continue;
            if (!this.validateExtension(rawFile.fileName)) {
              validationSkipped.push(rawFile.fileName);
              continue;
            }

            const normalized = await this.normalizePluginPayload(rawFile);
            if (!this.validateNotEmpty(normalized.sizeBytes, normalized.fileName)) {
              validationSkipped.push(normalized.fileName);
              continue;
            }
            if (!this.validateSize(normalized.sizeBytes, normalized.fileName)) {
              validationSkipped.push(normalized.fileName);
              continue;
            }

            validFiles.push(normalized);
            await new Promise(resolve => requestAnimationFrame(resolve));
          }

          this.finalizeValidation({
            countLimitSkipped,
            validationSkipped,
            totalInput: items.length
          });

          this.$emit('uploadFile', validFiles);

          await this.$nextTick();
          if (this.$el) {
            this.$el.offsetHeight;
          }
        } catch (error) {
          logger.error(() => `Failed to process upload payload: ${error}`);
          this.setError('UPLOAD_PAYLOAD_ERROR', String(error?.message || error));
          this.$emit('fileError', {code: 'UPLOAD_PAYLOAD_ERROR', message: this.errorText});
        }
      },

      async readBrowserFiles(fileList) {
        const allFiles = Array.from(fileList || []);
        const acceptCount = this.checkCountLimit(allFiles.length);
        const limited = allFiles.slice(0, acceptCount);
        const countLimitSkipped = allFiles.length - acceptCount;

        const validFiles = [];
        const validationSkipped = [];
        for (const file of limited) {
          if (!this.validateExtension(file.name)) {
            validationSkipped.push(file.name);
            continue;
          }
          if (!this.validateNotEmpty(file.size, file.name)) {
            validationSkipped.push(file.name);
            continue;
          }
          if (!this.validateSize(file.size, file.name)) {
            validationSkipped.push(file.name);
            continue;
          }

          const buffer = await file.arrayBuffer();
          validFiles.push({
            uint8Array1: new Uint8Array(buffer),
            fileName: file.name,
            sizeBytes: file.size,
            mimeType: file.type || 'application/octet-stream'
          });
        }

        this.finalizeValidation({
          countLimitSkipped,
          validationSkipped,
          totalInput: allFiles.length
        });

        this.$emit('uploadFile', validFiles);
      },

      async onInputChange(event) {
        this.clearError();
        const files = event.target.files;

        if (!files || !files.length) {
          this.resetNativeInput();
          return;
        }

        await this.readBrowserFiles(files);
        this.resetNativeInput();
      },

      async onDrop(event) {
        this.isDragOver = false;
        this.clearError();

        const files = event.dataTransfer?.files;
        if (!files || !files.length) return;

        await this.readBrowserFiles(files);
      }
    }
  };
</script>

<style scoped>
.upload-files {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  width: 100%;
  min-height: 72px;
  padding: 16px 20px;
  border: 1px dashed #b9d8c8;
  border-radius: 12px;
  transition: border-color .2s ease, background-color .2s ease;
  box-sizing: border-box;
}

.upload-files_dragover {
  border-color: #40c686;
  background-color: rgba(64, 198, 134, 0.08);
}

.upload-files__main {
  display: flex;
  align-items: center;
}

.upload-files input {
  display: none;
}

.upload-files__btn {
  white-space: nowrap;
  flex-shrink: 0;
}

.upload-files__description {
  margin-left: 20px;
  font-size: 13px;
  line-height: 18px;
  color: #535353;
}

.upload-files__error-block {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed #e4d3d1;
}

.upload-files__error {
  display: block;
  font-size: 12px;
  line-height: 16px;
  color: #d94236;
}

.upload-files__error-details {
  margin-top: 6px;
  font-size: 12px;
  line-height: 18px;
  color: #535353;
}

.upload-files__error-details summary {
  cursor: pointer;
  color: #666;
  outline: none;
  user-select: none;
}

.upload-files__error-details summary:hover {
  color: #2d2d2d;
}

.upload-files__error-types {
  margin-top: 6px;
  word-break: break-word;
}
</style>
