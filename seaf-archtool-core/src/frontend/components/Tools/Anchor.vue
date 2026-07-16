<!--
  Copyright (C) 2023 Sber

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.

  Maintainers:
      Romasha <r.piontik@mail.ru>

  Contributors:
      Romasha <r.piontik@mail.ru> - 2022
-->

<template>
  <a v-bind:id="id" dochub-anchor />
</template>

<script>
  export default {
    name: 'Anchor',
    props: {
      id: { type: String, default: '' }
    },
    data() {
      return {
      };
    }
  };
</script>

<style scoped>
</style>
