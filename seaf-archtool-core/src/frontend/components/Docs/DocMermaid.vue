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
      Navasardyan Suren, Sber - 2022
      R.Piontik <r.piontik@mail.ru> - 2022
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2025
-->

<template>
  <box
    style="overflow-x: auto;"
    v-bind:errors="errors"
    v-bind:path="path"
    v-on:doc-contextmenu="showContextMenu">
    <div v-html="svg" />
  </box>
</template>

<script>
  import mermaid from 'mermaid';
  import mustache from 'mustache';
  import mindmap from '@mermaid-js/mermaid-mindmap';
  import crc16 from '@global/helpers/crc16';

  import requests from '@front/helpers/requests';
  import href from '@front/helpers/href';

  import DocMixin from './DocMixin';

  import {diagram} from '@mermaid-js/mermaid-mindmap/dist/diagram-definition.ae1f7a29.js';
  import {diagram as architecture_diagram} from 'mermaid/dist/chunks/mermaid.core/architectureDiagram-3BPJPVTR';
  import {diagram as blockDiagram} from 'mermaid/dist/chunks/mermaid.core/blockDiagram-GPEHLZMM';
  import {diagram as c4Diagram} from 'mermaid/dist/chunks/mermaid.core/c4Diagram-AAUBKEIU';
  import {diagram as classDiagram} from 'mermaid/dist/chunks/mermaid.core/classDiagram-4FO5ZUOK';
  import {diagram as classDiagram_v2} from 'mermaid/dist/chunks/mermaid.core/classDiagram-v2-Q7XG4LA2';
  import {render as coseBilkentDiagram} from 'mermaid/dist/chunks/mermaid.core/cose-bilkent-S5V4N54A';
  import {render as dagreDiagram} from 'mermaid/dist/chunks/mermaid.core/dagre-BM42HDAG';
  import {diagram as diagramDiagram} from 'mermaid/dist/chunks/mermaid.core/diagram-2AECGRRQ';
  import {diagram as diagramDiagram_2} from 'mermaid/dist/chunks/mermaid.core/diagram-5GNKFQAL';
  import {diagram as diagramDiagram_3} from 'mermaid/dist/chunks/mermaid.core/diagram-KO2AKTUF';
  import {diagram as diagramDiagram_4} from 'mermaid/dist/chunks/mermaid.core/diagram-LMA3HP47';
  import {diagram as diagramDiagram_5} from 'mermaid/dist/chunks/mermaid.core/diagram-OG6HWLK6';
  import {diagram as erDiagram} from 'mermaid/dist/chunks/mermaid.core/erDiagram-TEJ5UH35';
  import {diagram as flowDiagram} from 'mermaid/dist/chunks/mermaid.core/flowDiagram-I6XJVG4X';
  import {diagram as ganttDiagram} from 'mermaid/dist/chunks/mermaid.core/ganttDiagram-6RSMTGT7';
  import {diagram as gitGraphDiagram} from 'mermaid/dist/chunks/mermaid.core/gitGraphDiagram-PVQCEYII';
  import {diagram as infoDiagram} from 'mermaid/dist/chunks/mermaid.core/infoDiagram-5YYISTIA';
  import {diagram as ishikawaDiagram} from 'mermaid/dist/chunks/mermaid.core/ishikawaDiagram-YF4QCWOH';
  import {diagram as journeyDiagram} from 'mermaid/dist/chunks/mermaid.core/journeyDiagram-JHISSGLW';
  import {diagram as kanbanDiagram} from 'mermaid/dist/chunks/mermaid.core/kanban-definition-UN3LZRKU';
  import {diagram as mindmapDiagram} from 'mermaid/dist/chunks/mermaid.core/mindmap-definition-RKZ34NQL';
  import {diagram as pieDiagram} from 'mermaid/dist/chunks/mermaid.core/pieDiagram-4H26LBE5';
  import {diagram as quadrantDiagram} from 'mermaid/dist/chunks/mermaid.core/quadrantDiagram-W4KKPZXB';
  import {diagram as requirementDiagram} from 'mermaid/dist/chunks/mermaid.core/requirementDiagram-4Y6WPE33';
  import {diagram as sankeyDiagram} from 'mermaid/dist/chunks/mermaid.core/sankeyDiagram-5OEKKPKP';
  import {diagram as sequenceDiagram} from 'mermaid/dist/chunks/mermaid.core/sequenceDiagram-3UESZ5HK';
  import {diagram as stateDiagram} from 'mermaid/dist/chunks/mermaid.core/stateDiagram-AJRCARHV';
  import {diagram as stateDiagram_v2} from 'mermaid/dist/chunks/mermaid.core/stateDiagram-v2-BHNVJYJU';
  import {diagram as timelineDiagram} from 'mermaid/dist/chunks/mermaid.core/timeline-definition-PNZ67QCA';
  import {diagram as vennDiagram} from 'mermaid/dist/chunks/mermaid.core/vennDiagram-CIIHVFJN';
  import {diagram as wardleyDiagram} from 'mermaid/dist/chunks/mermaid.core/wardleyDiagram-YWT4CUSO';
  import {diagram as xychartDiagram} from 'mermaid/dist/chunks/mermaid.core/xychartDiagram-2RQKCTM6';

  /*
  mermaid.initialize({
    startOnLoad:true
  });
  */

  mermaid.initialize({
    flowchart: {
      htmlLabels: false
    },
    htmlLabels: false
  });


  /* костыль, но вебпак я не поборол.
  * динамически подгружаемые модули засовывает в чанки
  * а загружать чанки наши плагины не умеют
  * поэтому прописал нужные динамические jsники статически
  */
  /* eslint-disable no-console */
  function never_used() {
    console.log(diagram);
    console.log(architecture_diagram);
    console.log(c4Diagram);
    console.log(classDiagram);
    console.log(classDiagram_v2);
    console.log(dagreDiagram);
    console.log(diagramDiagram);
    console.log(diagramDiagram_2);
    console.log(diagramDiagram_3);
    console.log(diagramDiagram_4);
    console.log(diagramDiagram_5);
    console.log(erDiagram);
    console.log(flowDiagram);
    console.log(ganttDiagram);
    console.log(gitGraphDiagram);
    console.log(infoDiagram);
    console.log(ishikawaDiagram);
    console.log(journeyDiagram);
    console.log(kanbanDiagram);
    console.log(mindmapDiagram);
    console.log(pieDiagram);
    console.log(quadrantDiagram);
    console.log(requirementDiagram);
    console.log(sankeyDiagram);
    console.log(sequenceDiagram);
    console.log(stateDiagram);
    console.log(stateDiagram_v2);
    console.log(timelineDiagram);
    console.log(vennDiagram);
    console.log(wardleyDiagram);
    console.log(xychartDiagram);
    console.log(blockDiagram);
    console.log(coseBilkentDiagram);
  }
  /* eslint-enable no-console */

  export default {
    name: 'DocMermaid',
    mixins: [DocMixin],
    data() {
      return {
        svg: null
      };
    },
    mounted() {
      if (!window.as_mindmap) {
        mermaid.registerExternalDiagrams([mindmap]).then(() => {
          window.as_mindmap = true;
        });
      }
    },
    methods: {
      load_all_dependencies() {
        never_used();
      },
      refresh() {
        // Получаем шаблон документа
        this.sourceRefresh().then(() => {
          requests.request(this.url).then(({ data }) => {
            const id = crc16(data + Date.now());
            let source = this.isTemplate
              ? mustache.render(data, this.source.dataset)
              : data;
            const cb = (svgGraph) => {
              // Генерируем ссылки т.к. Mermaid для C4 Model отказывается это делать сам
              // eslint-disable-next-line no-useless-escape
              this.svg = svgGraph.replace(/\!\[([^\]]*)\]\(([^\)]*)\)/g, (match, text, url)=> {
                return `<a href="${encodeURI(url)}">${text}<a>`;
              })
                + `<!-- ${id} -->`; // Без соли не работает ререндеринг тех же данных

              this.$nextTick(() => href.elProcessing(this.$el));
            };
            const drawDiagram = async function() {
              const { svg } = await mermaid.render(`buffer${id}`, source);
              cb(svg);
            };
            drawDiagram();
          }).catch((e) => this.error = e);
        });
      }
    }
  };
</script>
