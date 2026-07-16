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
  <v-menu
    v-model="menu"
    location="bottom end"
    v-bind:offset="8"
    v-bind:close-on-content-click="false"
    v-bind:transition="false"
    content-class="file-status-center__menu">
    <template #activator="{ props }">
      <v-list-item
        v-if="activator === 'menu-item'"
        class="file-status-center__menu-list-item"
        v-bind="props">
        <template #prepend>
          <v-badge
            v-bind:content="badgeText"
            v-bind:model-value="pendingCount > 0"
            color="orange"
            overlap>
            <v-icon>mdi-file-document-multiple-outline</v-icon>
          </v-badge>
        </template>
        <v-list-item-title>{{ menuTitle }}</v-list-item-title>
      </v-list-item>

      <v-btn
        v-else
        icon
        class="file-status-center__btn"
        title="Мои файлы"
        v-bind="props">
        <v-badge
          v-bind:content="badgeText"
          v-bind:model-value="pendingCount > 0"
          color="orange"
          overlap>
          <v-icon>mdi-file-document-multiple-outline</v-icon>
        </v-badge>
      </v-btn>
    </template>

    <v-card width="620" class="pa-0">
      <v-toolbar elevation="0" density="compact" color="#f7faf8">
        <v-toolbar-title class="text-subtitle-1 font-weight-medium">Мои файлы</v-toolbar-title>
        <v-spacer />
        <div class="file-status-center__summary">Файлы ({{ filteredFiles.length }})</div>
        <v-btn icon size="small" v-bind:loading="loading" v-on:click="refresh">
          <v-icon>mdi-refresh</v-icon>
        </v-btn>
      </v-toolbar>

      <div class="file-status-center__filters">
        <v-btn-toggle v-model="selectedFilter" mandatory density="compact">
          <v-btn size="small" value="all">Все</v-btn>
          <v-btn size="small" value="new">Новые</v-btn>
          <v-btn size="small" value="errors">С ошибками</v-btn>
          <v-btn size="small" value="active">В обработке</v-btn>
          <v-btn size="small" value="ready">Готовые</v-btn>
        </v-btn-toggle>
      </div>

      <div class="file-status-center__content">
        <div v-if="error" class="file-status-center__empty text-error">{{ error }}</div>

        <div v-else-if="loading && !files.length" class="file-status-center__empty">
          Загрузка статусов...
        </div>

        <div v-else-if="!files.length" class="file-status-center__empty">
          У вас пока нет загруженных файлов.
        </div>

        <div v-else-if="!filteredFiles.length" class="file-status-center__empty">
          По выбранному фильтру файлов нет.
        </div>

        <div v-else class="file-status-center__list">
          <file-status-row
            v-for="file in visibleFiles"
            v-bind:key="file.fileId"
            v-bind:file="file"
            v-bind:highlight-type="highlights[file.fileId] ? highlights[file.fileId].type : null"
            v-bind:recheck-in-progress="!!recheckingFileIds[file.fileId]"
            v-on:download="downloadFile"
            v-on:recheck-upload="onRecheckUpload"
            v-on:recheck-download="onRecheckDownload" />
          <div v-if="hasMoreToShow" class="file-status-center__show-more">
            <v-btn size="small" variant="text" color="primary" v-on:click="showMore">
              Показать ещё ({{ filteredFiles.length - visibleLimit }})
            </v-btn>
          </div>
        </div>
      </div>
    </v-card>
  </v-menu>
</template>

<script>
  import {
    getMyFiles,
    recheckDownload,
    recheckUpload,
    requestDownload,
    requestDownloadGate
  } from '@front/components/Uploader/lib/helpers/asyncFile.api.js';
  import {
    isTerminalUploadStatus
  } from '@front/components/Uploader/lib/helpers/fileStatus.utils.js';
  import { saveDownloadedFile } from '@front/components/Uploader/lib/helpers/fileDownload.js';
  import { getLoggerWithTag } from '@global/logger/v2/logger.mjs';
  import env, { Plugins } from '@front/helpers/env';
  import FileStatusRow from '@front/components/Account/FileStatusRow.vue';
  import {
    highlightSignature,
    HIGHLIGHT_TYPE,
    isRejectedStatus,
    isTerminalErrorStatus,
    isReadyStatus,
    isPassedStatus
  } from '@front/components/Account/fileHighlight.js';

  const logger = getLoggerWithTag('f/c/A/FileStatusCenter');
  const SEEN_STORAGE_KEY = 'seaf-file-status-center-seen';
  const FILES_CACHE_STORAGE_KEY = 'seaf-file-status-center-files-cache';
  const FILES_CACHE_MAX_ITEMS = 200;
  const HIGHLIGHT_MS = 30000;
  const FOREGROUND_POLL_MS = 40000;
  const BACKGROUND_POLL_MS = 50000;

  export default {
    name: 'FileStatusCenter',
    components: { FileStatusRow },
    props: {
      activator: {
        type: String,
        default: 'icon'
      },
      menuTitle: {
        type: String,
        default: 'Мои файлы'
      }
    },
    data() {
      return {
        menu: false,
        loading: false,
        error: '',
        files: [],
        timer: null,
        backgroundTimer: null,
        pollActive: false,
        backgroundPollActive: false,
        pruneTimer: null,
        seenKeys: {},
        previousFilesById: {},
        enrichedCache: {},
        highlights: {},
        firstSeenAt: {},
        selectedFilter: 'all',
        visibleLimit: 30,
        recheckingFileIds: {}
      };
    },
    computed: {
      pendingCount() {
        const seen = this.seenKeys || {};
        return this.files.filter(file => !seen[file.__seenKey]).length;
      },
      badgeText() {
        return this.pendingCount > 9 ? '9+' : this.pendingCount;
      },

      filteredFiles() {
        const highlights = this.highlights || {};

        switch (this.selectedFilter) {
          case 'new':
            return this.files.filter(file => highlights[file.fileId]?.type === HIGHLIGHT_TYPE.NEW);
          case 'errors':
            return this.files.filter(file => file.__hasError);
          case 'active':
            return this.files.filter(file => !file.__isReady && !file.__hasError);
          case 'ready':
            return this.files.filter(file => file.__isReady);
          default:
            return this.files;
        }
      },

      visibleFiles() {
        return this.filteredFiles.slice(0, this.visibleLimit);
      },

      hasMoreToShow() {
        return this.filteredFiles.length > this.visibleLimit;
      }
    },

    watch: {
      menu(value) {
        if (value) {
          this.visibleLimit = 30;
          requestAnimationFrame(() => {
            if (!this.menu) return;
            this.markAllAsSeen();
            this.refresh({ silent: this.files.length > 0 });
            this.startPolling();
            this.stopBackgroundPolling();
          });
        } else {
          this.stopPolling();
          this.ensureBackgroundPolling();
        }
      },
      selectedFilter() {
        this.visibleLimit = 30;
      }
    },

    async mounted() {
      this.seenKeys = this.readSeenKeys();
      this.hydrateFilesFromCache();
      await this.refresh({ silent: true });
      this.ensureBackgroundPolling();
    },

    beforeUnmount() {
      this.stopPolling();
      this.stopBackgroundPolling();
      this.stopPruneTimer();
    },

    methods: {
      readSeenKeys() {
        try {
          const raw = window.localStorage.getItem(SEEN_STORAGE_KEY);
          if (!raw) return {};

          const parsed = JSON.parse(raw);

          if (Array.isArray(parsed)) {
            const map = {};
            parsed.forEach(key => {
              if (key) map[key] = true;
            });
            return map;
          }

          return parsed && typeof parsed === 'object' ? parsed : {};
        } catch (e) {
          logger.error(() => 'Не удалось прочитать просмотренные файлы из localStorage', e);
          return {};
        }
      },

      persistSeenKeys(keysMap) {
        const source = keysMap || {};
        const validKeys = new Set(this.files.map(file => file.__seenKey));
        const pruned = {};
        for (const key of Object.keys(source)) {
          if (validKeys.has(key)) pruned[key] = source[key];
        }
        this.seenKeys = pruned;
        window.localStorage.setItem(SEEN_STORAGE_KEY, JSON.stringify(pruned));
      },

      readCachedFiles() {
        try {
          const raw = window.localStorage.getItem(FILES_CACHE_STORAGE_KEY);
          if (!raw) return null;
          const parsed = JSON.parse(raw);
          return Array.isArray(parsed?.files) ? parsed.files : null;
        } catch (e) {
          logger.warn(() => 'Не удалось прочитать кеш списка файлов', e);
          return null;
        }
      },

      persistFilesCache(filesRaw) {
        try {
          const trimmed = (filesRaw || []).slice(0, FILES_CACHE_MAX_ITEMS);
          window.localStorage.setItem(FILES_CACHE_STORAGE_KEY, JSON.stringify({
            files: trimmed,
            savedAt: Date.now()
          }));
        } catch (e) {
          logger.warn(() => 'Не удалось сохранить кеш списка файлов', e);
        }
      },

      hydrateFilesFromCache() {
        const cached = this.readCachedFiles();
        if (!cached || !cached.length) return;

        const now = Date.now();
        const nextFirstSeen = { ...(this.firstSeenAt || {}) };
        cached.forEach(file => {
          if (!nextFirstSeen[file.fileId]) {
            const backendTs = Date.parse(file.updatedAt || file.downloadValidatedAt || '') || 0;
            nextFirstSeen[file.fileId] = backendTs || now;
          }
        });
        this.firstSeenAt = nextFirstSeen;

        const sorted = cached.slice().sort((a, b) => {
          const aSeen = nextFirstSeen[a.fileId] || 0;
          const bSeen = nextFirstSeen[b.fileId] || 0;
          if (aSeen !== bSeen) return bSeen - aSeen;
          return String(a.fileId || '').localeCompare(String(b.fileId || ''));
        });

        this.files = sorted.map(file => this.enrichFile(file));
      },

      fileSeenKey(file) {
        return [
          file?.fileId || '',
          file?.status || '',
          file?.downloadValidatedAt || ''
        ].join('|');
      },

      markAllAsSeen() {
        const seen = this.seenKeys || {};
        const unseen = this.files.filter(file => !seen[file.__seenKey]);
        if (!unseen.length) return;

        const nextSeen = { ...seen };
        unseen.forEach(file => {
          nextSeen[file.__seenKey] = true;
        });
        this.persistSeenKeys(nextSeen);
      },

      hasActiveFiles() {
        return this.files.some(file => !isTerminalUploadStatus(file.status));
      },

      updateHighlights(enrichedFiles) {
        const nextPrev = {};
        const nextHighlights = { ...(this.highlights || {}) };
        const seen = this.seenKeys || {};
        const now = Date.now();

        (enrichedFiles || []).forEach(file => {
          const prev = this.previousFilesById[file.fileId];
          const currentSig = file.__highlightSignature;
          const prevSig = prev ? prev.__highlightSignature : null;
          const alreadySeen = !!seen[file.__seenKey];

          if (!prev && !alreadySeen) {
            nextHighlights[file.fileId] = { type: HIGHLIGHT_TYPE.NEW, expiresAt: now + HIGHLIGHT_MS };
          } else if (prev && prevSig !== currentSig && !alreadySeen) {
            nextHighlights[file.fileId] = {
              type: file.__hasError ? HIGHLIGHT_TYPE.ERROR : HIGHLIGHT_TYPE.UPDATED,
              expiresAt: now + HIGHLIGHT_MS
            };
          }

          nextPrev[file.fileId] = file;
        });

        this.previousFilesById = nextPrev;
        this.highlights = nextHighlights;
        this.pruneHighlights();
        this.ensurePruneTimer();
      },

      enrichFile(file) {
        const sig = highlightSignature(file);
        const cached = this.enrichedCache[file.fileId];
        if (cached && cached.__highlightSignature === sig) {
          return cached;
        }

        const validatorRows = [
          ...Object.entries(file.uploadValidators || {}).map(([key, value]) => ({ key, ...value })),
          ...Object.entries(file.downloadValidators || {}).map(([key, value]) => ({ key: `download:${key}`, ...value }))
        ];
        const status = String(file.status || '').toUpperCase();
        const isRejected = isRejectedStatus(status);
        const isReady = isReadyStatus(status) && !!file.uploadValidated;
        const hasError = isRejected || validatorRows.some(v => isRejectedStatus(String(v.status || '').toUpperCase()));

        const enriched = {
          ...file,
          __seenKey: this.fileSeenKey(file),
          __highlightSignature: sig,
          __isRejected: isRejected,
          __isReady: isReady,
          __hasError: hasError,
          __statusClass: this.computeStatusClass(status, file.uploadValidated),
          __formattedSize: this.formatBytes(file.sizeBytes),
          __formattedCreatedAt: file.createdAt ? this.formatInstant(file.createdAt) : '',
          __formattedDownloadValidatedAt: file.downloadValidatedAt ? this.formatInstant(file.downloadValidatedAt) : '',
          __sourceLine: this.computeSourceLine(file),
          __sourceDetails: this.computeSourceDetails(file),
          __sourceLink: this.computeSourceLink(file),
          __sourceLinkTarget: this.computeSourceLinkTarget(file),
          __validatorRows: validatorRows.map(v => ({
            ...v,
            __class: this.computeValidatorClass(status, v.status)
          }))
        };

        const frozen = Object.freeze(enriched);
        this.enrichedCache[file.fileId] = frozen;
        return frozen;
      },

      computeStatusClass(upperStatus, uploadValidated) {
        if (isTerminalErrorStatus(upperStatus)) {
          return 'file-status-row__status_error';
        }
        if (isReadyStatus(upperStatus) && !!uploadValidated) {
          return 'file-status-row__status_ok';
        }
        return 'file-status-row__status_pending';
      },

      computeValidatorClass(fileStatusUpper, status) {
        if (isRejectedStatus(fileStatusUpper)) {
          return 'file-status-row__validator_muted';
        }
        const s = String(status || '').toUpperCase();
        if (isPassedStatus(s)) return 'file-status-row__validator_ok';
        if (isRejectedStatus(s)) return 'file-status-row__validator_error';
        return 'file-status-row__validator_pending';
      },

      computeSourceLine(file) {
        if (file.pageObjectId && file.rowId) return `Источник: ${file.pageObjectId} · строка ${file.rowId}`;
        if (file.pageObjectId) return `Страница: ${file.pageObjectId}`;
        return '';
      },

      computeSourceDetails(file) {
        return file.pageTitle ? `Загружен из: ${file.pageTitle}` : '';
      },

      computeSourceLink(file) {
        if (!file.pageUrl) return '';
        const raw = String(file.pageUrl).trim();
        if (!raw) return '';
        if (env.isPlugin(Plugins.idea)) return raw;
        const hashIndex = raw.indexOf('#');
        if (raw.startsWith('file:///url=main') && hashIndex >= 0) return raw.slice(hashIndex);
        return raw;
      },

      computeSourceLinkTarget(file) {
        if (env.isPlugin(Plugins.idea)) return '_self';
        const url = this.computeSourceLink(file);
        if (!url || url.startsWith('#') || url.startsWith('file://')) return '_self';
        return '_blank';
      },

      pruneEnrichedCache(keepIds) {
        const next = {};
        for (const id of keepIds) {
          if (this.enrichedCache[id]) next[id] = this.enrichedCache[id];
        }
        this.enrichedCache = next;
      },

      pruneHighlights() {
        const now = Date.now();
        const entries = Object.entries(this.highlights || {});
        if (!entries.length) return;

        const cleaned = {};
        let expired = 0;
        for (const [key, value] of entries) {
          if (value?.expiresAt > now) {
            cleaned[key] = value;
          } else {
            expired += 1;
          }
        }

        if (expired === 0) return;

        this.highlights = cleaned;
        if (Object.keys(cleaned).length === 0) {
          this.stopPruneTimer();
        }
      },

      ensurePruneTimer() {
        if (this.pruneTimer) return;

        const values = Object.values(this.highlights || {});
        if (!values.length) return;

        const nextExpiresAt = values.reduce(
          (min, highlight) => Math.min(min, highlight?.expiresAt ?? Infinity),
          Infinity
        );
        if (!Number.isFinite(nextExpiresAt)) return;

        const delay = Math.max(250, nextExpiresAt - Date.now());
        this.pruneTimer = setTimeout(() => {
          this.pruneTimer = null;
          this.pruneHighlights();
          this.ensurePruneTimer();
        }, delay);
      },

      stopPruneTimer() {
        if (this.pruneTimer) {
          clearTimeout(this.pruneTimer);
          this.pruneTimer = null;
        }
      },

      showMore() {
        this.visibleLimit += 30;
      },

      async refresh(options = {}) {
        const { silent = false } = options;

        if (!silent) this.loading = true;
        this.error = '';

        try {
          const response = await getMyFiles();
          const filesRaw = response?.files || [];

          const now = Date.now();
          const nextFirstSeen = { ...(this.firstSeenAt || {}) };
          const activeIds = new Set(filesRaw.map(f => f.fileId));
          filesRaw.forEach(file => {
            if (!nextFirstSeen[file.fileId]) {
              const backendTs = Date.parse(file.updatedAt || file.downloadValidatedAt || '') || 0;
              nextFirstSeen[file.fileId] = backendTs || now;
            }
          });
          Object.keys(nextFirstSeen).forEach(id => {
            if (!activeIds.has(id)) delete nextFirstSeen[id];
          });
          this.firstSeenAt = nextFirstSeen;

          const raw = filesRaw.slice().sort((a, b) => {
            const aSeen = nextFirstSeen[a.fileId] || 0;
            const bSeen = nextFirstSeen[b.fileId] || 0;
            if (aSeen !== bSeen) return bSeen - aSeen;
            return String(a.fileId || '').localeCompare(String(b.fileId || ''));
          });

          const enriched = raw.map(file => this.enrichFile(file));
          this.pruneEnrichedCache(enriched.map(f => f.fileId));

          this.updateHighlights(enriched);

          const prev = this.files;
          const unchanged = prev.length === enriched.length
            && prev.every((f, i) => f === enriched[i]);
          if (!unchanged) {
            this.files = enriched;
          }

          this.persistFilesCache(filesRaw);

          if (this.menu) {
            this.markAllAsSeen();
          }

          if (this.menu && !this.hasActiveFiles()) {
            this.stopPolling();
          }
        } catch (e) {
          logger.error(() => 'Не удалось загрузить список файлов пользователя', e);
          this.error = this.files.length
            ? 'Не удалось обновить список — показаны данные из кеша'
            : 'Не удалось загрузить список файлов';
        } finally {
          if (!silent) this.loading = false;
        }
      },

      startPolling() {
        this.stopPolling();
        if (!this.hasActiveFiles()) return;
        this.pollActive = true;
        this.scheduleNextPoll();
      },

      scheduleNextPoll() {
        if (!this.pollActive) return;
        if (!this.hasActiveFiles()) {
          this.stopPolling();
          return;
        }
        this.timer = setTimeout(async() => {
          this.timer = null;
          if (!this.pollActive) return;
          if (this.menu && this.hasActiveFiles()) {
            try {
              await this.refresh({ silent: true });
            } catch (e) {
              logger.error(() => 'Ошибка в цикле поллинга статусов файлов', e);
            }
          }
          this.scheduleNextPoll();
        }, FOREGROUND_POLL_MS);
      },

      ensureBackgroundPolling() {
        this.stopBackgroundPolling();
        if (!this.hasActiveFiles()) return;
        this.backgroundPollActive = true;
        this.scheduleNextBackgroundPoll();
      },

      scheduleNextBackgroundPoll() {
        if (!this.backgroundPollActive) return;
        this.backgroundTimer = setTimeout(async() => {
          this.backgroundTimer = null;
          if (!this.backgroundPollActive || this.menu) return;
          try {
            await this.refresh({ silent: true });
          } catch (e) {
            logger.error(() => 'Ошибка в цикле фонового поллинга статусов файлов', e);
          }
          if (!this.hasActiveFiles()) {
            this.stopBackgroundPolling();
            return;
          }
          this.scheduleNextBackgroundPoll();
        }, BACKGROUND_POLL_MS);
      },

      stopBackgroundPolling() {
        this.backgroundPollActive = false;
        if (this.backgroundTimer) {
          clearTimeout(this.backgroundTimer);
          this.backgroundTimer = null;
        }
      },

      stopPolling() {
        this.pollActive = false;
        if (this.timer) {
          clearTimeout(this.timer);
          this.timer = null;
        }
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

      formatInstant(value) {
        if (!value) return '';
        try {
          let date;
          if (typeof value === 'number') {
            date = new Date(value * 1000);
          } else if (typeof value === 'string') {
            const trimmed = value.trim();
            if (/^\d+$/.test(trimmed)) {
              date = new Date(Number(trimmed) * 1000);
            } else {
              date = new Date(trimmed);
            }
          } else {
            date = new Date(value);
          }
          if (Number.isNaN(date.getTime())) return String(value);

          const day = String(date.getDate()).padStart(2, '0');
          const month = String(date.getMonth() + 1).padStart(2, '0');
          const year = date.getFullYear();
          const hours = String(date.getHours()).padStart(2, '0');
          const minutes = String(date.getMinutes()).padStart(2, '0');
          const seconds = String(date.getSeconds()).padStart(2, '0');
          return `${day}.${month}.${year} ${hours}:${minutes}:${seconds}`;
        } catch (e) {
          return String(value);
        }
      },

      parseFilename(contentDisposition) {
        if (!contentDisposition) {
          return null;
        }

        const encodedFilenameMatch = /filename\*\s*=\s*UTF-8''([^;\s\r\n]+)/i.exec(contentDisposition);

        if (encodedFilenameMatch) {
          try {
            return decodeURIComponent(encodedFilenameMatch[1]);
          } catch (error) {
            logger.error('Failed to decode filename from Content-Disposition', {contentDisposition, encodedFilename: encodedFilenameMatch[1], error});
          }
        }
        const plainFilenameMatch = /filename\s*=\s*"?([^";\r\n]+)"?/i.exec(contentDisposition);
        if (plainFilenameMatch) {
          const rawFilename = plainFilenameMatch[1].trim().replace(/^"|"$/g, '');
          if (!rawFilename) {
            return null;
          }
          try {
            return decodeURIComponent(rawFilename);
          } catch (error) {
            logger.error('Failed to decode plain filename from Content-Disposition', {contentDisposition, rawFilename, error});
            return rawFilename;
          }
        }

        return null;
      },

      markRecheckInProgress(fileId, inProgress) {
        const next = { ...this.recheckingFileIds };
        if (inProgress) {
          next[fileId] = true;
        } else {
          delete next[fileId];
        }
        this.recheckingFileIds = next;
      },

      async onRecheckUpload(file) {
        if (!file?.fileId) return;
        if (this.recheckingFileIds[file.fileId]) return;
        this.markRecheckInProgress(file.fileId, true);
        try {
          await recheckUpload(file.fileId);
          logger.info(() => `Recheck upload запущен для ${file.fileId}`);
          await this.refresh({ silent: true });
          this.ensureBackgroundPolling();
        } catch (e) {
          logger.error(() => `Не удалось запустить recheck upload для ${file.fileId}`, e);
          this.error = `Не удалось перезапустить проверку загрузки: ${e?.message || e}`;
        } finally {
          this.markRecheckInProgress(file.fileId, false);
        }
      },

      async onRecheckDownload(file) {
        if (!file?.fileId) return;
        if (this.recheckingFileIds[file.fileId]) return;
        this.markRecheckInProgress(file.fileId, true);
        try {
          await recheckDownload(file.fileId);
          logger.info(() => `Recheck download запущен для ${file.fileId}`);
          await this.refresh({ silent: true });
          this.ensureBackgroundPolling();
        } catch (e) {
          logger.error(() => `Не удалось запустить recheck download для ${file.fileId}`, e);
          this.error = `Не удалось перезапустить проверку скачивания: ${e?.message || e}`;
        } finally {
          this.markRecheckInProgress(file.fileId, false);
        }
      },

      async downloadFile(file) {
        try {
          logger.info(() => `Запуск скачивания файла ${file.fileId}`);

          const response = await requestDownload(file.fileId);

          if (response.statusCode !== 200) {
            logger.info(() => `Скачивание файла ${file.fileId} пока недоступно, запросим gate`);
            await requestDownloadGate(file.fileId);
            await this.refresh();
            return;
          }

          const contentDisposition =
            response.headers?.['content-disposition'] ||
            response.headers?.['Content-Disposition'] ||
            '';

          const fileName = this.parseFilename(contentDisposition) || file.originalName || `${file.fileId}.bin`;

          logger.info(() => `Сохраняем файл ${file.fileId} как ${fileName}`);
          await saveDownloadedFile(response, fileName);
        } catch (e) {
          logger.error(() => `Скачивание пока недоступно для ${file.fileId}`, e);
        }
      }
    }
  };
</script>

<style scoped>
.file-status-center__menu-list-item {
  min-height: 40px;
}

.file-status-center__btn {
  margin-right: 4px;
}

.file-status-center__filters {
  padding: 10px 12px 0;
}

.file-status-center__summary {
  font-size: 12px;
  color: #586069;
  margin-right: 12px;
}

.file-status-center__content {
  max-height: 78vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.file-status-center__empty {
  padding: 16px;
  color: #586069;
}

.file-status-center__list {
  padding: 12px;
  max-height: 70vh;
  overflow-y: auto;
  overflow-x: hidden;
  overscroll-behavior: contain;
  contain: layout paint;
}

.file-status-center__show-more {
  display: flex;
  justify-content: center;
  padding: 8px 0 4px;
}

</style>
