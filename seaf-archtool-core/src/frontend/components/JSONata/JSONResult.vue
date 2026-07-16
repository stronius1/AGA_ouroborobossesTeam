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
-->

<template>
  <pre class="language-json" tabindex="0">
    <div class="buttons">
      <v-btn type="button" class="save-btn" icon v-on:click="saveResult"><v-icon>{{ 'mdi-content-save' }}</v-icon></v-btn>
      <copy-button v-bind:get-copied-text="getJsonataToCopy" />
    </div>
    <code v-if="!isReload" class="language-json">{{ jsoncode }}</code>
  </pre>
</template>

<script>
  import downloadHelper from '@front/helpers/download.js';
  import CopyButton from '@front/components/Buttons/CopyButton.vue';

  export default {
    name: 'JSONResult',
    components: {
      CopyButton
    },
    props: {
      jsoncode: {
        type: [String],
        default: ''
      }
    },
    data() {
      return {
        isReload: true
      };
    },
    watch: {
      jsoncode() {
        this.reload();
      }
    },
    mounted() {
      this.reload();
    },
    methods: {
      reload() {
        this.isReload = true;
        this.$nextTick(() => {
          this.isReload = false;
          if (this.jsoncode.length < 5000) {
            // eslint-disable-next-line no-undef
            this.$nextTick(() => Prism.highlightAll());
          }
        });
      },
      async saveResult() {
        const data = window.btoa(unescape(encodeURIComponent(this.jsoncode)));
        downloadHelper.download(`data:text/plain;base64,${data}`, 'jsonata-output.txt');
      },
      getJsonataToCopy() {
        return this.jsoncode;
      }
    }
  };
</script>

<style scoped>
  .language-json {
    position: relative;
  }

  .buttons {
    position: absolute;
    top: 15px;
    right: 15px;
    display: flex;
    gap: 12px;
    /* New stacking context is needed here, because Vuetify 4 did something unnatural with the buttons and they freeze the browser in some cases if left in common context. */
    z-index: 1;
  }
</style>
