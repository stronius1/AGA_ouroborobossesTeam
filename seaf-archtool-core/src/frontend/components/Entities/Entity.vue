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
      R.Piontik <r.piontik@mail.ru> - 2024
      Vladislav Nefedov <clay.zenx@gmail.com>, Sber - 2023
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2024
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
      Artyom Prilip <artyom.prilip@gmail.com>, Sber - 2026
-->

<template>
  <div v-bind:style="placeHolderStyle">
    <doc
      v-if="!isParamsInvalid && !refresh"
      v-bind:path="presentationPath"
      v-bind:params="entityParams"
      v-bind:context-menu="toSwitchPres" />
    <v-alert v-if="isParamsInvalid && profileLoaded" type="error" style="white-space: pre-wrap;">
      Сущность: {{ entity }}<br>
      Представление: {{ presentation }}<br>
      {{ isParamsInvalid.name }}:<br>
      {{ isParamsInvalid.error }}
    </v-alert>
  </div>
</template>

<script>
  import Ajv from 'ajv';
  import ajvLocalize from 'ajv-i18n/localize/ru';

  import doc from '@front/components/Docs/DocHubDoc.vue';
  import query from '@front/manifest/query';

  import { uploadDocument } from './EntityUpload';
  import {startPageEvent} from '@front/clickstream/pageEvent.ts';
  import {logComponentTree} from '@front/logger/loggerExtension';

  export default {
    name: 'Entity',
    components: {
      doc
    },
    props: {
      entity: {
        type: String,
        default: undefined
      },
      presentation: {
        type: String,
        default: undefined
      },
      params: {
        type: Object,
        default: undefined
      }
    },
    data() {
      return {
        switchedPresentation: null,
        refresh: false,
        profile: null,
        refresher: null,
        profileLoaded: false,
        menu: {
          show: false,
          x: 0,
          y: 0
        },
        minHeight: null
      };
    },
    computed: {
      // Возвращает презентацию с учетом выбора пользователя
      currentPresentation() {
        return this.switchedPresentation || this.presentation;
      },
      // Стиль на время перестройки документа
      placeHolderStyle() {
        return this.minHeight ? { 'min-height': `${this.minHeight}px` } : undefined;
      },
      // Валидируем входящие параметры, если контракт на параметры определен
      isParamsInvalid() {
        return this.isInvalidParamsToPres(this.presProfile?.params);
      },
      // Все доступные презентации сущности для переключения
      toSwitchPres() {
        const items = this.profile?.presentations || {};
        const result = [];
        if (this.profile?.presentation_context_menu_filter?.omitAll) {
          return result;
        }
        Object.keys(items).forEach((id) => {
          if (id === this.currentPresentation) return;
          const schema = items[id].params;
          if (!schema || !this.isInvalidParamsToPres(schema)) {
            if (this.profile?.presentation_context_menu_filter?.omit?.includes(id) || items[id].contextMenu === 'omit') {
              return;
            }
            result.push({
              id,
              title: items[id].title || id,
              on: () => this.onSelectedPres(id)
            });
          }
        });
        return result;
      },
      // Получаем профиль представления
      presProfile() {
        return this.profile?.presentations?.[this.presentation] || {};
      },
      // Формируем параметры для документа
      entityParams() {
        return this.params || (this.$route.params && this.$route.query);
      },
      presentationPath() {
        return `${this.entityPath}/presentations/${this.currentPresentation}`;
      },
      entityPath() {
        return `/entities/${this.entity}`;
      },
      manifest() {
        return this.$store.state.manifest;
      }
    },
    watch: {
      entityParams() {
        logComponentTree('Entity watch entityParams', this);
        this.registerPageLoadIfRoot();
        this.reloadProfile();
      },
      entityPath() {
        logComponentTree('Entity watch entityPath', this);
        this.registerPageLoadIfRoot();
        this.reloadProfile();
      },
      manifest() {
        logComponentTree('Entity watch manifest', this);
        this.registerPageLoadIfRoot();
        !this.refresher && this.reloadProfile().then(() => this.$nextTick(this.refreshPres));
      },
      currentPresentation() {
        logComponentTree('Entity watch currentPresentation', this);
        this.registerPageLoadIfRoot();
        this.reloadProfile(false);
      }
    },
    mounted() {
      logComponentTree('Entity mounted', this);
      this.registerPageLoadIfRoot();
      this.reloadProfile();
    },
    created() {
      logComponentTree('Entity created', this);
      this.registerPageLoadIfRoot();
      this.reloadProfile();
    },
    updated() {
      logComponentTree('Entity updated', this);
      this.registerPageLoadIfRoot();
    },
    methods: {
      /**
       * Проверяем, является ли этот Entity первым, то есть корневым (а не вложенным)
       * Если он корневой, то регистрируем начало отрисовки страницы
       */
      registerPageLoadIfRoot() {
        let rootEntity;
        let currentUid = this.$.uid;
        let current = this;
        // идем вверх по parent компонентов в поисках самого первого Entity
        while (current) {
          if (current.$options.name === 'Entity') {
            rootEntity = current;
          }
          current = current.$parent;
        }
        let rootEntityUid = rootEntity?.$.uid;
        if (rootEntity && currentUid === rootEntityUid) {
          // если uid текущего компонента и самого первого в цепочек равны, значит это корневой компонент и
          // начинаем отслеживать время отрисовки
          startPageEvent(
            rootEntity.$props.entity,
            rootEntityUid
          );
        }
      },
      makeDataLakeID(path) {
        return `("${path.slice(1).split('/').join('"."')}")`;
      },
      // Перезагружает профиль сущности
      reloadProfile(resetSwitchedPresentation = true) {
        return new Promise((success, reject) => {
          if (this.refresher) clearTimeout(this.refresher);
          this.profileLoaded = false;
          this.refresher = setTimeout(() => {
            if (resetSwitchedPresentation) this.switchedPresentation = null;
            const dateLakeId = this.makeDataLakeID(this.entityPath);
            query.expression(dateLakeId).evaluate()
              .then((data) => {
                // Проверяем, что результат запроса не устарел
                if (dateLakeId === this.makeDataLakeID(this.entityPath)) {
                  this.profile = data;
                  this.profileLoaded = true;
                  success(data);
                }
              })
              .catch((e) => { this.error = e; reject(e); })
              .finally(() => this.refresher = null);
          }, 100);

        });
      },
      // Принудительное обновление представления
      refreshPres() {
        this.refresh = true;
        this.minHeight = this.$el.clientHeight;
        this.$nextTick(() => this.refresh = false);
      },
      // Проверка схемы презентации на параметры
      isInvalidParamsToPres(schema) {
        if (schema) {
          try {
            const rules = new Ajv({ allErrors: true });
            const validator = rules.compile(schema);
            if (validator(this.entityParams)) return false;
            ajvLocalize(validator.errors);
            return {
              name: 'Ошибка валидации параметров',
              error: JSON.stringify(validator.errors, null, 4)
            };
          } catch (e) {
            return {
              name: 'Ошибка описания схемы',
              error: e
            };
          }
        } else return false;
      },
      // Выбор альтернативной презентации
      onSelectedPres(presentation) {
        const presProfile = this.profile?.presentations?.[presentation] || {};
        // Если презентация направлена на выгрузку данных, генерируем их без переключения презентации
        if (presProfile.type.toLowerCase() === 'upload') {
          const path = `/entities/${this.entity}/presentations/${presentation}`;
          uploadDocument(presProfile, path, this.entityParams, this.manifest);
        } else { // Иначе переключаем презентацию
          this.switchedPresentation = presentation;

          // this.$router.push({
          //   path: `/entities/${this.entity}/${presentation}`,
          //   query: this.$route.query
          // });

          this.refreshPres();
        }
      }
    }
  };
</script>
