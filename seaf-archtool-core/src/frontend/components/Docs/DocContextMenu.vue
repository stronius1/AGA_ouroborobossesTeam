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
  <v-menu
    v-model="isShow"
    v-bind:target="[x, y]"
    style="z-index: 1000"
    location="bottom">
    <v-list>
      <v-list-item
        v-for="item in items"
        v-bind:key="item.id"
        link
        v-on:click="item.on(item)">
        <v-list-item-title>
          {{ item.title }}
        </v-list-item-title>
      </v-list-item>
    </v-list>
  </v-menu>
</template>

<script>
  export default {
    name: 'DocContextMenu',
    props: {
      items: {
        type: Array,
        default: () => []
      },
      x: {
        type: Number,
        default: 0
      },
      y: {
        type: Number,
        default: 0
      },
      modelValue: {
        type: Boolean,
        default: false
      }
    },
    emits: ['update:modelValue'],
    computed: {
      isShow: {
        get() { return this.modelValue; },
        set(value) { this.$emit('update:modelValue', value); }
      }
    }
  };
</script>
