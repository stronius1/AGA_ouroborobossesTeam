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
      Navasardyan Suren, Sber - 2023
      Rostislav Kabalin <kabalin2009@yandex.ru> - 2022
      R.Piontik <r.piontik@mail.ru> - 2025
      Artyom Prilip <artyom.prilip@gmail.com>, Sber - 2026
-->

<script>
  import SwaggerUI from 'swagger-ui';
  import DocMixin from './DocMixin';
  import { getAsyncApiContext } from '@front/helpers/misc';
  import env from '@front/helpers/env';
  import requests from '@front/helpers/requests';

  const ROOT_PATH_DEEP = 16;
  const ROOT_PATH = 'http://null/$/$/$/$/$/$/$/$/$/$/$/$/$/$/$/$/$root';

  export default {
    name: 'DocSwagger',
    mixins: [DocMixin],
    data() {
      return {
        dom_id : `swagger-${Date.now()}-${Math.round(Math.random() * 10000)}`,
        data: null
      };
    },
    computed: {
      getClass() {
        return this.inline ? 'sgr-inline' : 'sgr-not-inline';
      }
    },
    watch: {
      isPrintVersion() {
        const el = document.getElementById(this.dom_id);
        el.innerHTML = '';
        this.$nextTick(this.swaggerRender);
      }
    },
    methods: {
      refresh() {
        getAsyncApiContext.call(this, true);
      },

      async proxy(url) {
        let target = new URL(String(url));
        const base = new URL(ROOT_PATH);
        if (target.hostname !== base.hostname) return url;
        let deep = target.pathname.split('$/').length - 1;
        target = '../'.repeat(ROOT_PATH_DEEP - deep) + target.pathname.slice(deep * 2 + 1);
        const response = await requests.request(target, this.url);
        const data = typeof response.data === 'string' ? response.data : JSON.stringify(response.data);
        const type = response.headers?.['content-type'] || response?.['content-type'] ||  'plain/text';
        const blobData = new Blob([data], {type});
        return URL.createObjectURL(blobData);
      },

      async requestInterceptor(request) {
        if (request.url === ROOT_PATH) {
          const rootData = new Blob([typeof this.data === 'string' ? this.data : JSON.stringify(this.data) ], {type: 'application/json'});
          return {
            ...request,
            url: URL.createObjectURL(rootData)
          };
        } else return {
          ...request,
          url: await this.proxy(request.url)
        };
      },
      swaggerRender() {
        if (this.url) {
          SwaggerUI({
            dom_id: `#${this.dom_id}`,
            url: ROOT_PATH,
            deepLinking: !env.isPlugin(),
            docExpansion: this.isPrintVersion ? 'full' : 'list',
            presets: [
              SwaggerUI.presets.apis
            ],
            requestInterceptor: this.requestInterceptor
          });
        }
      }
    }
  };
</script>

<template>
  <box
    v-bind:id="dom_id"
    v-bind:class="getClass"
    v-bind:errors="errors"
    v-bind:path="path"
    v-on:doc-contextmenu="showContextMenu" />
</template>

<style>
  .sgr-not-inline {
    padding: 16px;
    width: 100%;
  }

  .swagger-ui .opblock .opblock-summary-path {
      min-width: 100px;
  }
</style>
