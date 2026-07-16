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
  <g>
    <rect
      rx="4"
      v-bind:x="x"
      v-bind:y="y"
      v-bind:width="width"
      v-bind:height="height"
      class="info" />
    <switch>
      <foreignObject
        class="info-text"
        v-bind:x="x + 4"
        v-bind:y="y + 6"
        v-bind:width="width - 4"
        v-bind:height="height - 6">
        <p>{{ text }}</p>
      </foreignObject>
      <text
        class="info-text"
        v-bind:x="x + 4"
        v-bind:y="y + 4">
        {{ text }}
      </text>
    </switch>
  </g>
</template>

<script>
  export default {
    name: 'DHSchemaTrack',
    props: {
      x: {
        type: Number,
        default: 4
      },
      y: {
        type: Number,
        default: 4
      },
      width: {
        type: Number,
        default: 400
      },
      height: {
        type: Number,
        default: 48
      },
      text: {
        type: String,
        default: 'Тут пусто :('
      }
    },
    data() {
      return {
      };
    },
    computed: {
    },
    methods: {
    }
  };

</script>

<style scoped>

.info {
  fill: rgb(52, 149, 219);;
  stroke:rgb(52, 149, 219);
  opacity: 0.7;
  stroke-linejoin:round;
  stroke-width:2px;
  -webkit-filter: drop-shadow( 3px 3px 2px rgba(0, 0, 0, .7));
  filter: drop-shadow( 3px 3px 2px rgba(0, 0, 0, .7));
  transition: all 0.25s ease-in;
}

.info-text {
  stroke:#fff;
  color:#fff;
  line-height: 20px;
  font-size: 18px;
  font-weight: 600;
  transition: all 0.25s ease-in;
}

</style>
