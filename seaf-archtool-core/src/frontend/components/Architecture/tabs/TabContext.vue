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
      R.Piontik <r.piontik@mail.ru> - 2023
-->

<template>
  <v-card
    style="
      overflow: hidden;
      position: relative;
      min-height: 600px;
    ">
    <v-card-title>
      <v-icon start>mdi-link</v-icon>
      <span class="title">Контексты</span>
    </v-card-title>
    <v-select
      v-model="context"
      v-bind:items="contexts"
      item-title="title"
      item-value="id"
      return-object
      class="d-flex"
      cols="12"
      sm="12"
      style="margin: 0 12px 0px 12px" />
    <v-card-text
      class="headline font-weight-bold"
      style="
        position: absolute;
        top: 108px;
        left: 0;
        bottom: 0;
        right: 0;
        overflow: auto;
      ">
      <entity entity="contexts" presentation="plantuml" v-bind:params="params" style="min-height:calc(100% - 24px)" />
    </v-card-text>
  </v-card>
</template>

<script>

  import Entity from '@front/components/Entities/Entity.vue';

  export default {
    name: 'TabContexts',
    components: {
      Entity
    },
    props: {
      defaultContext: { type: Object, default: null },
      contexts: { type: Array, default: () => ([]) }
    },
    data() {
      return {
        selected : null,
        currentContext: 0
      };
    },
    computed: {
      params() {
        if (this.context.type === 'component')
          return {
            'dh-context-id': 'SELF',
            componentId: this.context.id
          };
        else return {
          'dh-context-id': this.context.id
        };
      },
      context: {
        get() {
          if (!this.selected) {
            return this.defaultContext || this.contexts[0];
          }

          return this.selected;
        },
        set(value) {
          this.selected = value;
        }
      }
    },
    watch: {
      contexts() {
        this.selected = null;
      }
    }
  };
</script>
