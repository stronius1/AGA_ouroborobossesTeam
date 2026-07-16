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
-->

<template>
  <v-alert type="error" icon="mdi-alert-circle">
    <pre class="err-exp-output" v-html="errorExplain" />
  </v-alert>
</template>

<script>
  export default {
    name: 'JSONataErrorExplainer',
    props: {
      error: {
        type: Object,
        default: null
      },
      query: {
        type: Object,
        default: null
      }
    },
    data() {
      return {
      };
    },
    computed: {
      errorExplain() {
        if (this.error) {
          const pos = this.error.position;
          let result = (`Error: ${this.error.message}`).replaceAll('\\n', '\n');
          if (this.query) result += `\n\n${this.query.slice(0, pos)} <span style="color:red"> ${this.query.slice(pos)} </span>`;
          return result;
        }
        return null;
      }
    }
  };
</script>

<style>
  .v-alert__content {
    max-width: 100%;
  }
  .err-exp-output {
    width: 100%;
    resize: none;
    padding: 0px;
    overflow-y: auto;
    word-wrap: break-word;
  }
</style>
