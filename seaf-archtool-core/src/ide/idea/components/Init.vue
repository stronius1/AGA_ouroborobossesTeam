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
      Rostislav Kabalin <kabalin2009@yandex.ru>

  Contributors:
      R.Piontik <r.piontik@mail.ru> - 2024
      Rostislav Kabalin <kabalin2009@yandex.ru> - 2022
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
-->

<template>
  <div
    style="width: 400px; height: 300px; left: 50%; top: 50%; position: absolute; margin-left: -150px; margin-top: -150px; text-align:center;">
    Корневой манифест архитектуры <strong>seaf.yaml (или dochub.yaml)</strong> не обнаружен или не может быть загружен.<br><br>
    Если файл существует, пожалуйста, проверьте его содержимое на наличие ошибок. Если манифест отсутствует, воспользуйтесь помощником для его создания.
    <br><br>
    <v-btn variant="flat" color="primary" v-on:click="initEmptyProject">Создать пустой файл</v-btn>
    <br><br>
    <v-btn variant="flat" color="primary" v-on:click="initExampleProject">Создать пример</v-btn>
  </div>
</template>

<script>

  export default {
    name: 'Empty',
    data() {
      return {};
    },
    methods: {
      initEmptyProject() {
        window.$PAPI.initProject();
      },
      initExampleProject() {
        window.$PAPI.initProject('example');
      }
    }
  };
</script>

<style scoped>


</style>
