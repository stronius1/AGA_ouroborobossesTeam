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
      R.Piontik <r.piontik@mail.ru> - 2023
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
      Artyom Prilip <artyom.prilip@gmail.com>, Sber - 2026
-->

<template>
  <div>
    <dochub-doc v-bind:path="path" />
  </div>
</template>

<script>
  import env from '@front/helpers/env';
  import { startPageEvent } from '@front/clickstream/pageEvent.ts';

  export default {
    name: 'MainPage',
    data() {
      return {};
    },
    computed: {
      path() {
        return '/docs/' + (env.rootDocument || 'dochub.welcome');
      }
    },
    created() {
      // Main не является компонентов документом и при этом является страницей - создаем событие загрузки страницы
      startPageEvent(this.name, this.$.uid);
    }
  };
</script>
