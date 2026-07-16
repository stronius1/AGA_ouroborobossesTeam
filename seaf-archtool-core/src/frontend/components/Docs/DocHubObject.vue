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
      R.Piontik <r.piontik@mail.ru> - 2024
      R.Piontik <r.piontik@mail.ru> - 2023
      R.Piontik <r.piontik@mail.ru> - 2022
      R.Piontik <r.piontik@mail.ru> - 2021
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
-->

<template>
  <div class="dochub-object" v-bind:style="{float:srcStruct?.float}">
    <dochub-doc
      v-if="isDocument"
      v-bind:path="documentPath"
      v-bind:document="srcStruct.subject"
      v-bind:alt="srcStruct.alt"
      v-bind:inline="inline"
      v-bind:params="srcStruct.params" />
    <dochub-context v-else-if="isContext" v-bind:context="srcStruct.subject" v-bind:alt="srcStruct.alt" v-bind:inline="inline" />
    <dochub-aspect v-else-if="isAspect" v-bind:aspect="srcStruct.subject" v-bind:alt="srcStruct.alt" v-bind:inline="inline" />
    <dochub-component v-else-if="isComponent" v-bind:component="srcStruct.subject" v-bind:alt="srcStruct.alt" v-bind:inline="inline" />
    <dochub-technology v-else-if="isTechnology" v-bind:technology="srcStruct.subject" v-bind:alt="srcStruct.alt" v-bind:inline="inline" />
    <dochub-radar v-else-if="isRadar" v-bind:section="srcStruct.subject" v-bind:alt="srcStruct.alt" v-bind:inline="inline" />
    <dochub-anchor v-else-if="isAnchor" v-bind:id="srcStruct.subject" v-bind:name="srcStruct.subject" v-bind:inline="inline" />
    <dochub-image v-else-if="isImage" v-bind:src="src" v-bind:alt="srcStruct.alt" v-bind:base-u-r-i="baseURI" v-bind:inline="inline" />
    <dochub-youtube v-else-if="isYoutube" v-bind:src="srcStruct.subject" v-bind:alt="srcStruct.alt" v-bind:base-u-r-i="baseURI" v-bind:inline="inline" />
    <dochub-entity v-else-if="isEntity" v-bind:entity="srcStruct.subject" v-bind:presentation="srcStruct.presentation" v-bind:params="srcStruct.params" v-bind:inline="inline" />
    <dochub-date-picker v-else-if="isDatePicker" v-bind:src="srcStruct.subject" v-bind:params="srcStruct.params" v-bind:inline="inline" />
    <div v-else>
      Что-то пошло не так :(
      <br>
      {{ srcStruct }}
    </div>
  </div>
</template>

<script>
  import requests from '@front/helpers/requests';
  import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

  const logger = getLoggerWithTag('f/c/D/DocHubObject');

  export default {
    name: 'DocHubObject',
    props: {
      src: { type: String, default: '' },
      alt: { type: String, default: '' },
      type: { type: String, default: '' },
      subject: { type: String, default: '' },
      baseURI: { type: String, default: '' },
      // Признак того, что объект встроен в другой объект
      inline: { type: Boolean, default: false }
    },
    computed: {
      // Параметры отображения встраиваемого объекта
      srcStruct() {
        const result = {
          type: this.type || 'image',
          subject: this.subject || this.src,
          params: {},
          float: 'none'
        };
        try {
          // eslint-disable-next-line no-debugger
          const source = this.src.toLowerCase();
          if (source.startsWith('@')) {
            const url = new URL(this.src.replace('@', '/'), requests.getSourceRoot());
            const path = url.pathname.split('/');
            result.type = path[1];
            result.subject = path[2];
            result.params = Object.fromEntries(url.searchParams);
            if ((result.type === 'document') && (result.subject.startsWith('blob:') || result.subject.slice(-1) === ':')) {
              // Если в субъекте http ссылка на объект, то разбираем ее отдельно
              result.subject = path.slice(2).join('/');
            } else {
              // Иначе воспринимаем как презентацию
              result.presentation = path[3];
            }
          } else if (source.startsWith('https://www.youtube.com/') || source.startsWith('https://youtu.be/')) {
            result.type = 'youtube';
            result.subject = this.src;
          }
        } catch (e) {
          logger.warn(() => '', e);
        }

        // Определяем форматирование объекта
        const alt = this.alt || '';
        switch(alt.substring(0,1)) {
          case '<':
            result.float = 'left';
            result.alt = alt.substring(1);
            break;
          case '>':
            result.float = 'right';
            result.alt = alt.substring(1);
            break;
          default:
            result.alt = alt;
        }
        return result;
      },
      isDocument() {
        return this.srcStruct?.type.toLowerCase() === 'document';
      },
      isContext() {
        return this.srcStruct?.type.toLowerCase() === 'context';
      },
      isAspect() {
        return this.srcStruct?.type.toLowerCase() === 'aspect';
      },
      isComponent() {
        return this.srcStruct?.type.toLowerCase() === 'component';
      },
      isTechnology() {
        return this.srcStruct?.type.toLowerCase() === 'technology';
      },
      isRadar() {
        return this.srcStruct?.type.toLowerCase() === 'radar';
      },
      isAnchor() {
        return this.srcStruct?.type.toLowerCase() === 'anchor';
      },
      isImage() {
        return this.srcStruct?.type.toLowerCase() === 'image';
      },
      isEntity() {
        return this.srcStruct?.type.toLowerCase() === 'entity';
      },
      isDatePicker() {
        return this.srcStruct?.type.toLowerCase() === 'datepicker';
      },
      isYoutube() {
        return this.srcStruct?.type.toLowerCase() === 'youtube';
      },
      documentPath() {
        const path = this.src.split('?')[0].replaceAll('@document/', '');
        return `/docs/${path}`;
      }
    }
  };
</script>

<style scoped>
.dochub-object :deep(.v-window) {
  overflow: visible;
}
</style>
