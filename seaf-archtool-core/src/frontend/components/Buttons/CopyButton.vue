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
      Sergeev Viktor, Sber

  Contributors:
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
      Artyom Prilip <artyom.prilip@gmail.com>, Sber - 2026
-->

<template>
  <v-btn
    type="button"
    class="save-btn"
    v-bind:title="title"
    v-bind:icon="copied ? 'mdi-check' : 'mdi-content-copy'"
    v-on:click="copyCode" />
</template>

<script>
  import writeToClipboard from '@front/helpers/clipboard.js';
  import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

  const logger = getLoggerWithTag('f/c/B/CopyButton');

  export default {
    name: 'CopyButton',
    props: {
      title: {
        type: String,
        default: 'Copy to clipboard'
      },
      // Функция для обновления текста, который попадет в буфер обмена
      getCopiedText: {
        type: Function,
        default: null
      }
    },
    data() {
      return {
        copied: false
      };
    },
    methods: {
      async copyCode() {
        try {
          await writeToClipboard(this.getCopiedText());
          this.copied = true;
          setTimeout(() => {
            this.copied = false;
          }, 2000);
        } catch (error) {
          logger.error(() => 'Copy button failed:', error);
        }
      }
    }
  };
</script>
