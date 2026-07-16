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
      R.Piontik <r.piontik@mail.ru> - 2024
-->

<template>
  <box
    class="space"
    v-bind:errors="errors"
    v-bind:path="path"
    v-on:doc-contextmenu="showContextMenu" />
</template>

<script>

  import { Network , DataSet } from 'vis-network/standalone/umd/vis-network.min';
  import DocMixin from './DocMixin';

  export default {
    name: 'DocNetwork',
    mixins: [DocMixin],
    data() {
      return {
        height: '400px'
      };
    },
    computed: {
      netData() {
        return this.source?.dataset;
      },
      isTemplate() {
        return true;
      }
    },
    watch: {
      netData() {
        this.network && this.network.destroy();
        this.network = new Network(this.$el, {
          nodes: new DataSet(this.netData?.nodes || []),
          edges: new DataSet(this.netData?.edges || [])
        }, Object.assign({
          // autoResize: true,
          locale: 'ru',
          clickToUse: true,
          layout: {
            randomSeed: 0
          },
          physics: {
            enabled: true,
            solver: 'repulsion'
          }
        }, this.netData?.options || {}));
      }
    },
    mounted() {
      this.height = `${this.$el.clientWidth * 0.6}px`;
    }
  };
</script>

<style scoped>

.space {
  padding: 0;
  aspect-ratio : 1 / 0.6;
  width: 100%;
  max-height: calc(100vh - 100px);
  min-width: 100%;
}

</style>
