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
      R.Piontik <r.piontik@mail.ru> - 2022
      R.Piontik <r.piontik@mail.ru> - 2021
-->

<template>
  <g>
    <circle class="ring-arc-3" cx="300" cy="300" r="300" />
    <circle class="ring-arc-2" cx="300" cy="300" r="260" />
    <circle class="ring-arc-1" cx="300" cy="300" r="200" />
    <circle class="ring-arc-0" cx="300" cy="300" r="110" />
  </g>
</template>

<script>

  export default {
    data() {
      return {
      };
    }
  };
</script>

<style scoped>

.section {
  padding: 0;
  height: 40vh;
}

svg circle.ring-arc-0 {
  stroke: none;
  fill: #bababa;
}

svg circle.ring-arc-1 {
  stroke: none;
  fill: #cacaca;
}

svg circle.ring-arc-2 {
  stroke: none;
  fill: #dadada;
}

svg circle.ring-arc-3 {
  stroke: none;
  fill: #eee;
}

svg text.line-text {
  font-weight: 700;
  text-transform: uppercase;
  fill: #000;
  font-size: 12px;
}

</style>
