/*
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
      R.Piontik <r.piontik@mail.ru> - 2025
      R.Piontik <r.piontik@mail.ru> - 2024
      R.Piontik <r.piontik@mail.ru> - 2023
      R.Piontik <r.piontik@mail.ru> - 2022
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2025
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
*/

import datasets from '@front/helpers/datasets';
import gateway from '@ide/gateway';
import uriTool from '@front/helpers/uri';
import requests from '@front/helpers/requests';
import {pageEventDocOnLoad, pageEventRegDoc} from '@front/clickstream/pageEvent.ts';
import {logComponentTree} from '@front/logger/loggerExtension';

const SOURCE_PENDING = 'pending';
const SOURCE_READY = 'ready';
const SOURCE_ERROR = 'error';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

const logger = getLoggerWithTag('f/c/D/DocMixin');

export default {
    components: {
        Box: {
            template: `
			<div v-on:contextmenu="onContextMenu">
				<v-alert v-for="error in errors" v-bind:key="error.key" type="error" style="line-height: 18px; overflow-x: auto;">
					Компонент: {{error.componentName}}<br>
					Источник: {{path}}<br><br>
					Ошибка:
					<div style="background-color:#FDD835; white-space: pre-wrap; padding: 8px; color: #000;" v-html="error.message">
					</div>
				</v-alert>
				<slot v-if="!errors.length"></slot>
			</div>`,
            props: {
                errors: {
                    type: Array,
                    default() {
                        return [];
                    }
                },
                path: {
                    type: String,
                    default: ''
                }
            },
            emits: ['doc-contextmenu'],
            methods: {
                onContextMenu(event) {
                    this.$emit('doc-contextmenu', event);
                }
            }
        }
    },
    methods: {
        // Сохраняет состояние отображения документа
        saveState() {
            this.state.scrollY = window.scrollY;
            this.state.scrollX = window.scrollX;
        },
        // Восстанавливает состояние отображение
        loadState() {
            logComponentTree('Mixin loadState', this);
            //loadState вызывается после отрисовки компонента документа, так что фиксируем отрисовку тут
            pageEventDocOnLoad();
            if (this.state.scrollY !== null) {
                window.scroll(this.state.scrollX, this.state.scrollY);
            }
        },
        makeDataLakeID(path) {
            return `("${path.slice(1).split('/').join('"."')}")`;
        },
        doRefresh() {
            this.error = null;
            if (this.source.refreshTimer) clearTimeout(this.source.refreshTimer);
            this.source.refreshTimer = setTimeout(() => this.refresh(), 100);
        },
        refresh() {
            this.sourceRefresh();
        },
        sourceRefresh() {
            return new Promise((success, reject) => {
                this.source.status = SOURCE_PENDING;
                this.source.dataset = null;
                if (this.isTemplate && this.profile?.source) {
                    const sourceBasePath = uriTool.getBaseURIOfPath(`${this.path}/source`) || this.baseURI;
                    this.source.provider.getData(null, this.profile, this.params, sourceBasePath)
                        .then((dataset) => {
                            this.source.dataset = dataset;
                            this.source.status = SOURCE_READY;
                            success(dataset);
                        })
                        .catch((e) => {
                            this.error = e;
                            this.source.status = SOURCE_ERROR;
                            reject(e);
                        })
                        .finally(() => {
                            this.$nextTick(() => this.loadState());
                        });
                } else {
                    success(this.source.dataset = null);
                    // регистрируем что компонент документа отрисован (один из вариантов, если не попали в ветку if)
                    pageEventDocOnLoad();
                }
            });
        },
        onChangeSource(data) {
            if (data) {
                this.saveState();
                for (const source in data) {
                    if (source === requests.getIndexURL(this.url)) {
                        this.doRefresh();
                    }
                }
            }
        },
        showContextMenu(event) {
            event.preventDefault();
            this.menu.show = false;
            this.menu.x = event.clientX;
            this.menu.y = event.clientY;
            this.$nextTick(() => {
                this.menu.show = true;
            });
        },
        appendError(error, componentName) {
            let message = (error?.message || error);
            if (error.response) {
                const description = error.response?.data?.error || JSON.stringify(error.response?.data);
                message = (description ? `<pre>${description}</pre>` : '');
                if (error.config) {
                    const link = error.config.url.toString();
                    message += `${message}<br><br>URL:<a href="${link}" target="_blank">${link}</a><br><br>`;
                }
            }
            let errorMessage = 'no error text';
            if (typeof message === 'string') {
                errorMessage = message?.slice(0, 1024)?.toString();
            }
            this.errors.push(
                {
                    key: Date.now(),
                    message: errorMessage,
                    componentName
                }
            );
        },
        clearErrors() {
            this.errors = [];
        }
    },
    computed: {
        id() {
            return this.path.split('/').pop();
        },
        isTemplate() {
            return this.profile?.template;
        },
        baseURI() {
            let result = uriTool.getBaseURIOfPath(this.path);
            result?.startsWith('res://') && (result = requests.expandResourceURI(result));
            return result;
        },
        contentBasePath() {
            return uriTool.getBaseURIOfPath(`${this.path}/${this.isTemplate ? 'template' : 'source'}`) || this.baseURI;
        },
        url() {
            let uri = this.profile.template || this.profile.source;
            //признак, что ссылка на source указывает на вложенность (что метаданные и контент в одном файле)
            let inlineContent = false;
            if (uri === '.') {
              inlineContent = true;
              uri = this.contentBasePath;
            }
            uri?.startsWith('res://') && (uri = requests.expandResourceURI(uri));
            let result = this.profile ? uriTool.makeURIByBaseURI(uri, this.contentBasePath).toString() : null;
            if (!result) return null;
            result += result.indexOf('?') > 0 ? '&' : '?';
            result += `id=${this.id}&path=${encodeURI(this.path)}&inlineContent=${inlineContent}`;
            return result;
        },
        isPrintVersion() {
            return this.toPrint || this.$store.state.isPrintVersion;
        }
    },
    props: {
        // Признак того, что документ встроен в другой документ
        inline: {
            type: Boolean,
            required: true
        },
        // Путь к данным профиля документа
        path: {
            type: String,
            required: true
        },
        // Параметры передающиеся в запросы документа
        params: {
            type: Object,
            required: true
        },
        // Признак рендеринга документа для печати
        toPrint: {
            type: Boolean,
            required: false,
            default: undefined
        },
        // Контекстное меню
        contextMenu: {
            type: Array,
            default() {
                return [];
            }
        },
        // Профиль документа
        profile: {
            type: Object,
            default() {
                return {};
            }
        }
    },
    data() {
        const provider = datasets();
        return {
            errors: [],
            error: null,
            state: {
                scrollY: null,
                scrollX: null
            },
            menu: {
                show: false,
                x: 0,
                y: 0
            },
            source: {
                provider,
                status: SOURCE_READY,
                dataset: null,
                refreshTimer: null
            }
        };
    },
    watch: {
        path() { this.doRefresh(); },
        params() { this.doRefresh(); },
        profile() { this.doRefresh(); },
        error(error) {
            if (error) {
                logger.error(() => `Ошибка запроса [${this.url}]`, error);
                this.appendError(error, this.$options?.name || 'unknown');
            } else
                this.clearErrors();
        }
    },
    created() {
        // Следим за обновлением документа
        logComponentTree('Mixin created', this);
        //Когда документ создается, регистрируем его в событии загрузки страницы clickstream
        pageEventRegDoc();
        gateway.appendListener('source/changed', this.onChangeSource);
    },
    unmounted() {
        gateway.removeListener('source/changed', this.onChangeSource);
    },
    mounted() {
        logComponentTree('Mixin mounted', this);
        this.doRefresh();
    }
};
