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
      R.Piontik <r.piontik@mail.ru> - 2023
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2023
      Vladislav Nefedov <clay.zenx@gmail.com>, Sber - 2024
      Nikolay Temnyakov <temnjakovn@gmail.com>, Sber - 2025
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025, 2026
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2025
-->

<template>
  <v-container class="desk" fluid>
    <splitpanes horizontal class="default-theme jsonata-splitpanes">
      <pane v-bind:size="40">
        <div class="console" ref="datasetSelectorContainer">
          <v-toolbar density="compact" elevation="0" height="min-content">
            <v-btn v-show="!autoExec" icon title="Выполнить" v-on:click="onExecute(true)">
              <v-icon>mdi-arrow-right-drop-circle</v-icon>
            </v-btn>
            <v-toolbar-title v-if="isLogFuncAvailable" class="title-hint">
              Используйте $log(value[, tag]) для трассировки запросов.
            </v-toolbar-title>
            <v-spacer />
            <v-autocomplete
              v-model="origin"
              multiple
              hide-details
              clearable
              v-bind:items="origins"
              v-bind:label="originLabel"
              title="Базовый источник данных"
              item-title="id"
              item-value="id"
              prepend-icon="mdi-semantic-web"
              single-line
              class="dataset-autocomplete"
              v-on:update:model-value="clearOriginMap">
              <template #selection="{ item }">
                <v-chip
                  closable
                  v-on:click:close="() => deleteOrigin(item.id)">
                  {{ item.id }}
                </v-chip>
              </template>
            </v-autocomplete>
            <v-menu location="bottom" v-bind:offset="8">
              <template #activator="{ props }">
                <v-btn icon v-bind="props">
                  <v-icon>mdi-dots-vertical</v-icon>
                </v-btn>
              </template>
              <v-list>
                <v-list-item>
                  <v-checkbox
                    v-model="autoExec" />
                  <v-list-item-title>Автовыполнение</v-list-item-title>
                </v-list-item>
              </v-list>
            </v-menu>
          </v-toolbar>
          <editor
            ref="editor"
            v-model="query"
            class="input" />
        </div>
      </pane>
      <pane v-bind:size="60">
        <pre v-if="error" class="output" v-html="errorExplain" />
        <div v-else class="output">
          <div class="log">
            <v-data-table
              v-bind:headers="logHeaders"
              v-bind:items="logItems"
              v-bind:search="search"
              v-bind:items-per-page="-1"
              hide-default-footer
              class="elevation-1 table">
              <template #item="{ item }">
                <tr
                  v-bind:class="(item.raw || item).id === selectedLog ? 'selected-log' : ''"
                  v-on:click="logOnClick(item.raw || item)">
                  <td>{{ (item.raw || item).moment }}</td>
                  <td>{{ (item.raw || item).tag }}</td>
                </tr>
              </template>
            </v-data-table>
          </div>
          <result class="result" v-bind:jsoncode="result" />
        </div>
      </pane>
    </splitpanes>
  </v-container>
</template>

<script>
  import cookie from 'vue-cookie';
  import env from '@front/helpers/env';
  import yaml from 'yaml';

  import query from '@front/manifest/query';
  import datasets from '@front/helpers/datasets';

  import editor from './JSONataEditor.vue';
  import result from './JSONResult.vue';
  import {Base64URLToUTF8} from '@front/helpers/strings';
  import { getLoggerWithTag } from '@global/logger/v2/logger.mjs';

  import { Splitpanes, Pane } from 'splitpanes';
  import 'splitpanes/dist/splitpanes.css';

  const logger = getLoggerWithTag('f/c/J/DevTool');

  const COOKIE_NAME_QUERY = 'json-dev-tool-query';
  const COOKIE_NAME_AUTOEXEC = 'json-dev-tool-autoexec';

  export default {
    name: 'JSONataDevTool',
    components: {
      editor,
      result,
      Splitpanes,
      Pane
    },
    props: {
      jsonataSource: {
        type: String,
        default: null
      }
    },
    data() {
      return {
        isLogFuncAvailable: !env.isBackendMode,
        query: cookie.get(COOKIE_NAME_QUERY) || localStorage.getItem('query_id') || '"Здесь введите JSONata запрос."',
        error: null,
        observer: null, // Таймер отложенного исполнения запросов
        search: '',
        jsonata: null,
        selectedLog: 0,
        autoExec: cookie.get(COOKIE_NAME_AUTOEXEC) === 'true',
        origin: null,   // Выбранный базовый источник
        //TODO: нужно в целом уйти от выборки массива к мапе в ориджинах
        originMap: null,
        origins: [],    // Список доступных источников данных
        logHeaders: [
          {
            title: 'Таймлайн',
            align: 'start',
            key: 'moment'
          },
          {
            title: 'Тэг',
            align: 'start',
            key: 'tag'
          }
        ],
        logItems: []
      };
    },
    computed: {
      errorExplain() {
        if (this.error.position) {
          const pos = this.error.position;
          return `Error: ${this.error.message}\n\n${this.query.slice(0, pos)}<span style="color:red">${this.query.slice(pos)} </span>`;
        } else if (typeof this.error === 'string') {
          return this.error;
        }
        return null;
      },
      result() {
        return this.logItems[this.selectedLog]?.value || '';
      },
      isLoading() {
        return this.$store.state.isReloading;
      },
      originLabel() {
        return this.originMap ? 'Origin вычислен в IDE' : 'origin';
      }
    },
    watch: {
      origin() {
        this.onExecute();
      },
      isLoading() {
        this.doAutoExecute();
      },
      autoExec(value) {
        value && this.onExecute();
        cookie.set(COOKIE_NAME_AUTOEXEC, value, 365);
      },
      query() {
        this.onExecute();
      },
      manifest() {
        this.refreshOrigins(); // Обновляем список источников данных, если архитектурный манифест изменился
        this.loadJsonataQuery(); // Переподтягиваем при необходимости jsonata запрос из источника
      },
      jsonataSource(value) {
        this.loadJsonataQuery(value);
      }
    },
    unmounted() {
      clearInterval(this.timer);
      this.datasetSelect?.removeEventListener('wheel', this.scrollHorizontally);
    },
    mounted() {
      this.doAutoExecute();
      this.refreshOrigins();
      this.loadJsonataQuery();

      this.timer = setInterval(() => {
        localStorage.setItem('query_id', this.query);
      }, 2000);

      this.datasetSelect = this.$refs.datasetSelectorContainer.querySelector('.v-field__field .v-field__input');
      this.datasetSelect?.addEventListener('wheel', this.scrollHorizontally, { passive: false });
    },
    methods: {
      scrollHorizontally(e) {
        e.currentTarget.scrollLeft += e.deltaY;
        e.preventDefault();
      },

      deleteOrigin(originId) {
        this.origin = this.origin.filter(id => id !== originId);
        this.originMap = null;
      },
      clearOrigin() {
        this.origin = null;
        this.originMap = null;
        this.doAutoExecute();
      },
      clearOriginMap() {
        this.originMap = null;
      },
      refreshOrigins() {
        const pipe = query.expression(`([(datasets.$spread().{
          "id": $keys()[0],
          "title": *.title
      })])`, null, null, true, { log: this.log});
        pipe.evaluate().then((data) => this.origins = data);
      },
      doAutoExecute() {
        if (!this.isLoading && this.autoExec) this.onExecute();
      },
      loadJsonataQuery(param_id) {
        const src = param_id || this.jsonataSource;
        if (!src) return;

        const srcSplitPos = src.search(':');
        const sourceSplitPos = src.indexOf(':', srcSplitPos + 1);
        const jType = src.substring(0, srcSplitPos);
        const jSource = sourceSplitPos !== -1 ? src.substring(sourceSplitPos + 1) : '';

        if (jType === 'file' || jType === 'selection' || jType === 'element') {
          this.query = Base64URLToUTF8(jSource);
        } else if (jType === 'source') {
          try {
            const data = Object.values(yaml.parse(Base64URLToUTF8(jSource)))[0];
            this.originMap = data.origin;
            if (!this.originMap) {
              this.origin = [];
            } else if (typeof this.originMap === 'string') {
              this.origin = [this.originMap];
            } else if (typeof this.originMap === 'object' && !Array.isArray(this.originMap)) {
              this.origin = [];
            }
            this.query = data.source;
          } catch (e) {
            logger.error(() => 'Error of parsing data from IDE (source request)', e);
          }
        }
      },
      logOnClick(item) {
        this.selectedLog = item.id;
      },
      log(value, tag) {
        this.logItems.push({
          id: this.logItems.length,
          moment: (((new Date()).getTime() - this.jsonata?.expOrigin?.trace?.start || 0) * 0.001).toFixed(5),
          value: value ? JSON.parse(JSON.stringify(value)) : value,
          tag
        });
        return value;
      },

      doExecute(context) {
        cookie.set(COOKIE_NAME_QUERY, this.query, 365);
        this.error = null;
        this.logItems = [];
        if (env.isBackendMode && this.origin?.length) {
          const origin = this.origin.length > 1
            ? this.origin.reduce((acc, ele) => {acc[ele] = ele; return acc;} ,{})
            : this.origin[0];
          datasets().getData(null, {
            origin: origin,
            source: `(${this.query})`,
            separateDatasets: true
          }).then((data) => {
            this.log(JSON.stringify(data, null, 4), 'END');
          }).catch((err) => this.error = err);
        } else {
          this.jsonata = query.expression(`(${this.query})`, null, null, true, { log: this.log});
          this.jsonata.evaluate(context).then((data) => {
            const result = JSON.stringify(data, null, 4);
            this.logItems.push({
              id: this.logItems.length,
              moment: ((this.jsonata?.expOrigin?.trace?.end - this.jsonata?.expOrigin?.trace?.start || 0) * 0.001).toFixed(5),
              tag: 'END',
              value: result
            });
            this.selectedLog = this.logItems.length - 1;
          }).catch((e) => this.error = e);
        }
      },
      onExecute(force) {
        this.observer && clearTimeout(this.observer);
        if (this.autoExec || force) {

          const request = async() => {
            this.observer = null;

            const getData = async(origin) => {
              if (origin.startsWith('(')) {
                return query.expression(origin).evaluate();
              } else {
                const path = `/datasets/${origin}`;
                const meta = await datasets().pathResolver(path);
                const subject = Object.assign({ _id: path.split('/').pop() }, meta.subject || {});
                const baseURI = meta.baseURI || '/';
                return datasets().parseSource(
                  meta.context,
                  origin,
                  subject,
                  undefined,
                  baseURI
                );
              }
            };

            if (this.origin && !env.isBackendMode) {
              let originData = null;
              if (this.originMap) {
                if (typeof this.originMap === 'string') {
                  originData = Promise.resolve(getData(this.originMap));
                } else if (typeof this.originMap === 'object' && !Array.isArray(this.originMap)) {
                  originData = Promise.all(Object.entries(this.originMap).map(async([key, value]) => [key, await getData(value)]))
                    .then(entries => Object.fromEntries(entries));
                } else {
                  // eslint-disable-next-line no-console
                  logger.error(() => `origin is not string or object: ${JSON.stringify(this.originMap)}`);
                  return;
                }
              } else {
                originData = Promise.all(this.origin.map(async(origin) => ({ [origin]: await getData(origin) })))
                  .then((data) => this.origin.length > 1 ? data : data[0]);

              }

              originData.then((data) => this.doExecute(data))
                .catch((e) => this.error = e);
            } else {
              this.doExecute();
            }
          };

          this.observer = setTimeout(request, force ? 10 : 500);
        }
      }
    }
  };
</script>

<style>
.dataset-autocomplete {
  max-width: 70%;
}

.console .title-hint {
  color: #333;
}

.desk {
  position: relative;
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: none;
  height: 100%;
  max-height: 100%;
  min-height: 0;
  padding: 0;
  overflow: hidden;
}

.jsonata-splitpanes {
  flex: 1 1 auto;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.jsonata-splitpanes .splitpanes__pane {
  min-height: 0;
  overflow: hidden;
}

.console {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.input {
  flex: 1 1 auto;
  display: block;
  width: 100%;
  height: auto;
  min-height: 0;
  padding: 4px;
  overflow: hidden;
  resize: none;
  border: solid 1px #eee;
}

.output {
  display: flex;
  width: 100%;
  height: 100%;
  min-height: 0;
  padding: 0;
  overflow: hidden;
  resize: none;
}

.log {
  flex: 0 0 30%;
  width: auto;
  height: 100%;
  max-height: 100%;
  overflow: auto;
}

.result {
  flex: 1 1 auto;
  width: auto;
  height: 100%;
  min-width: 0;
  padding: 4px;
  overflow: auto;
  margin: 0 !important;
  background-color: #f5f5f5;
}

.log .table {
  width: 100%;
}

.selected-log {
  background-color: rgb(52, 149, 219) !important;
}

.console .v-field__field .v-field__input {
  flex-wrap: nowrap;
  overflow-x: auto;
}

.statistics {
  height: 24px;
  background-color: #eee;
}

.stat-item {
  color: black;
  float: left;
  font-size: 12px;
  margin: 6px 0 6px 12px;
}

pre.output {
  display: block;
  overflow: auto;
  white-space: pre-wrap;
}

@media (max-width: 800px) {
  .output {
    flex-direction: column;
  }

  .log {
    flex: 0 0 8em;
    width: 100%;
    height: auto;
  }

  .result {
    width: 100%;
    height: auto;
    min-height: 0;
  }

  .log .table > tr > td {
    height: 1em;
  }
}
</style>
