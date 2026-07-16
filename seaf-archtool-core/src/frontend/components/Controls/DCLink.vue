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
      R.Piontik <r.piontik@mail.ru> - 2022
-->

<template>
  <span v-if="isVsCodeLink" v-bind:class="$style.link" v-on:click="onClickVsCodeLink">
    <slot />
  </span>

  <a v-else v-bind:href="href" v-bind:target="target || '_blank'" v-on:click="onClick">
    <slot />
  </a>
</template>

<script>

  export default {
    name: 'DCLink',
    props: {
      href: { type: String, default: '' },
      target: { type: String, default: '' }
    },
    data() {
      return {};
    },
    computed: {
      isVsCodeLink() {
        return this.href.includes('https://file+.vscode-resource.vscode-cdn.net');
      }
    },
    methods: {
      onClickVsCodeLink() {
        window.$PAPI.goto(this.href);
      },
      onClick(event) {
        const struct = (this.href || '').split(':/');
        if (struct[0] === 'plugin') {
          const url = new URL(this.href);
          window.$PAPI.goto(`plugin:${url.pathname}`, url.searchParams.get('entity'), url.searchParams.get('id'));
          event.preventDefault();
          return false;
        } else if ((this.href || '').split(':/').length == 1) {
          event.preventDefault();
          this.$router.push(this.href);
          return false;
        }
        return true;
      }
    }
  };
</script>

<style module>
  .link {
    cursor: pointer;
    color: #1976d2;
  }
</style>
