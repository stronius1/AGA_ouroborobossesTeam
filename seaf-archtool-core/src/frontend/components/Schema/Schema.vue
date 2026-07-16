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
      Artyom Prilip <artyom.prilip@gmail.com>, Sber - 2026
      mumg <maxim@muratov.net> - 2023
      Rostislav Kabalin <kabalin2009@yandex.ru> - 2022
      R.Piontik <r.piontik@mail.ru> - 2023
      R.Piontik <r.piontik@mail.ru> - 2022
      R.Piontik <r.piontik@mail.ru> - 2021
-->

<template>
  <plantuml
    v-bind:uml="uml"
    v-bind:postrender="postrender"
    v-bind:source-available="true"
    v-on:copysource="copyJsonSource" />
</template>

<script>
  import PlantUMLDSL from '!!raw-loader!@assets/plantuml_dsl.txt';
  import C4ModelDSL from '!!raw-loader!@assets/c4model_dsl.txt';
  import SberDSL from '!!raw-loader!@assets/sber_dsl.txt';
  import requests from '@front/helpers/requests';
  import uri from '@front/helpers/uri';
  import copyToClipboard from '@front/helpers/clipboard';
  import env from '@front/helpers/env';
  import PlantUML from './PlantUML';
  import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

  const logger = getLoggerWithTag('f/c/S/Schema');

  export default {
    name: 'Schema',
    components: {
      'plantuml': PlantUML
    },
    props: {
      schema: { type: Object, default: () => ({}) },
      baseURI: {   // Пусть к объекту контекста
        type: String,
        default: null
      },
      notation: { // Нотация
        type: String,
        default: 'PlantUML',
        validator: value => [
          'PlantUML',
          'С4Model',
          'Sber'
        ].indexOf(value) >= 0
      },
      orientation: { // Ориентация построения схемы
        type: String,
        default: 'horizontal', // По умолчанию - сверху в низ
        validator: value => [
          'vertical',
          'horizontal'
        ].indexOf(value) >= 0
      }
    },
    data() {
      return {
        uml: '',
        umlRequestId: 0
      };
    },
    computed: {
      extraLinks() {
        return !('extra' in this.schema) || (this.schema.extra !== false);
      },

      renderCore() {
        return this.$store.state.renderCore;
      },

      structure() {
        // Структура схемы
        const structure = {
          namespaces: {},
          links: {}
        };

        // Размещает компонент в структуре схемы
        const expandComponent = (component, extra) => {
          let namespaces = structure.namespaces;
          component.namespaces && component.namespaces.map((namespace) => {
            !namespaces.namespaces && (namespaces.namespaces = {});
            !namespaces.namespaces[namespace.id] && (namespaces.namespaces[namespace.id] = Object.assign({}, namespace));
            namespaces = namespaces.namespaces[namespace.id];
          });
          !namespaces.components && (namespaces.components = {});
          if (!extra || !namespaces.components[component.id]) {
            namespaces.components[component.id] = Object.assign({ extra }, component);
          }
        };

        (this.schema.components || []).map((component) => {
          // Разбираем компонент
          expandComponent(component, false);
          // Разбираем зависимости компонента
          (component.links || []).map((link) => {
            expandComponent(link, true);
            structure.links[`${component.id} ${link.direction} ${link.id}`] =
              Object.assign(link, { linkFrom: component.id, linkTo: link.id });
          /*
        structure.links[`[${component.id}] ${link.direction} [${link.id}]`] =
            Object.assign(link, { linkFrom: component.id, linkTo: link.id});
        */
          });
        });

        return structure;
      }
    },
    watch: {
      schema: {
        handler() {
          this.refreshUml();
        },
        deep: true
      },
      baseURI() {
        this.refreshUml();
      },
      notation() {
        this.refreshUml();
      },
      orientation() {
        this.refreshUml();
      },
      renderCore() {
        this.refreshUml();
      }
    },
    mounted() {
      this.refreshUml();
    },
    methods: {
      async refreshUml() {
        const requestId = ++this.umlRequestId;
        const uml = await this.buildUml();

        if (requestId === this.umlRequestId) {
          this.uml = uml;
        }
      },
      async buildUml() {
        if (!this.schema?.components) return '';

        let uml = '@startuml\n';

        // Определяем в какой нотации будем выводить схему
        let notation = this.notation;
        if (this.schema.uml && this.schema.uml.$notation) {
          notation = this.schema.uml.$notation;
        }

        switch ((env.renderCore || 'graphviz').toLowerCase()) {
          case 'smetana': uml += '!pragma layout smetana\n'; break;
          case 'elk': uml += '!pragma layout elk\n'; break;
          case 'graphviz': uml += '!pragma layout graphviz\n'; break;
        }
        if (this.schema?.uml?.$dsl) {
          try {
            const dsl = await requests.request(this.schema.uml.$dsl, this.baseURI);
            uml += dsl.data;
          } catch (e) {
            logger.error(() => `Не получилось подключить кастомный DSL ${this.schema.uml.$dsl}`);
            uml += `${PlantUMLDSL}\n`;
          }
        } else {
          switch (notation.toLowerCase()) {
            case 'sber':
              uml += `${SberDSL}\n`;
              break;
            case 'c4model':
              uml += `${C4ModelDSL}\n`;
              break;
            case 'plantuml':
            default:
              uml += `${PlantUMLDSL}\n`;
          }
        }
        this.orientation === 'horizontal' && (uml += 'left to right direction\n');
        if (this.schema) {
          if (this.schema.uml) {
            if (typeof this.schema.uml === 'string') {
              return this.schema.uml;
            } else if (this.schema.uml.$before) {
              uml += this.schema.uml.$before + '\n';
            }
          }

          const header = {
            title: `"${this.makeRef('context', this.schema.id, this.schema.title)}"`,
            author: this.schema.uml && this.schema.uml.$autor ? this.schema.uml.$autor : '',
            version: this.schema.uml && this.schema.uml.$version ? this.schema.uml.$version : '',
            moment: this.schema.uml && this.schema.uml.$moment ? this.schema.uml.$moment : ''
          };
          uml += `$Header(${header.title}, ${header.author}, ${header.version}, ${header.moment})\n`;
          // Готовим структуру схемы для рендеринга
          const structure = this.structure;

          // Разбираем архитектурные пространства
          const expandNamespace = (namespace) => {
            // Если область определена, выводим ее
            let result = '';
            let notEmpty = false;
            if (namespace.id) {
              const type = namespace.type ? `"${namespace.type}"` : '';
              const title = namespace.link ? `[[${namespace.link} ${namespace.title}]]` : namespace.title;
              result += `$Region(${namespace.id},"${title}", ${type}) {\n`;
            }
            // Если есть вложенные пространства, отображаем их тоже
            if (namespace.namespaces) {
              for (const namespaceID in namespace.namespaces) {
                const subCode = expandNamespace(namespace.namespaces[namespaceID]);
                if (subCode) {
                  notEmpty = true;
                  result += subCode;
                }
              }
            }
            // Формируем компоненты
            for (const componentID in namespace.components) {
              const component = namespace.components[componentID];
              if (!this.extraLinks && component.extra)
                continue;
              notEmpty = true;
              const title = this.makeRef('component', component.id, component.title);
              // Если компонент является системой, описываем его через DSL
              let entity = (component.entity || 'component').toString();
              // Формируем список аспектов
              const aspectList = [];
              (component.aspects || []).map((aspect) => {
                let aspectTitle = this.makeRef('aspect', aspect.id, aspect.title);
                aspectList.push(aspectTitle);
              });

              result += `$Entity("${entity}", "${title}", ${component.id} , ${component.type ? '"' + component.type + '"' : ''})\n`;
              aspectList.map((prop) => {
                result += `$EntityAspect("${entity}","${prop}")\n`;
              });
              if (component.is_context)
                result += `$EntityExpand("${entity}", ${component.id})\n`;
              result += `$EntityEnd("${entity}")\n`;
              result += '\n';
            }
            if (namespace.id && notEmpty) {
              result += '}\n';
            }
            return notEmpty ? result : null;
          };

          uml += expandNamespace(structure.namespaces) || '';

          // Строим связи
          for (const linkId in structure.links) {
            const link = structure.links[linkId];
            if (this.extraLinks || (() => {
              let namespace = structure.namespaces;
              for (let i = 0; i < link.namespaces.length; i++) {
                namespace = namespace.namespaces[link.namespaces[i].id];
              }
              return namespace.components[link.id] && !namespace.components[link.id].extra;
            })()) uml +=
              link.link_title
                ? (link.link_title.startsWith('[[') && link.link_title.endsWith(']]') ? (`${linkId}: ${link.link_title}\n`):(`${linkId}: [[http://#${encodeURI(linkId)} ${link.link_title || '⠀'}]]\n`))
                : `${linkId}: ⠀\n`;
          }
          this.schema.uml && this.schema.uml.$after && (uml += this.schema.uml.$after + '\n');
        }
        uml += '@enduml';

        return uml;
      },
      // Копирует данные для схемы в формате JSON
      copyJsonSource() {
        copyToClipboard(JSON.stringify(this.schema));
      },
      createSVGElement(tag) {
        return document.createElementNS('http://www.w3.org/2000/svg', tag);
      },
      getControlsByTarget(target) {
        let result;
        if (this.renderCore === 'smetana') {
          result = [target];
        } else {
          const linkID = target.getAttribute('data-link-selector');
          result = document.querySelectorAll(`[data-link-selector="${linkID}"]`);
        }
        return result;
      },

      onSelected(event) {
        const controls = this.getControlsByTarget(event.target);
        for (let i = 0; i < controls.length; i++)
          if (controls[i].classList.contains('selected'))
            controls[i].classList.remove('selected');
          else
            controls[i].classList.add('selected');
      },

      onOverLink(event) {
        const controls = this.getControlsByTarget(event.target);
        for (let i = 0; i < controls.length; i++)
          controls[i].classList.add('hover');
      },

      onOutLink(event) {
        const controls = this.getControlsByTarget(event.target);
        for (let i = 0; i < controls.length; i++)
          controls[i].classList.remove('hover');
      },
      postRenderDot(svg) {
        // Строим надписи на связях
        let prefix = 0;
        let defs = svg.querySelectorAll('defs')[0];
        if (!defs) {
          defs = this.createSVGElement('defs');
          svg.insertAfter && svg.insertAfter(0, defs);
        }
        for (const linkId in this.structure.links) {
          const link = this.structure.links[linkId];
          const selector = (() => {
            const isBack = link.direction.slice(0, 1) === '<';
            const isTo = link.direction.slice(-1) === '>';
            if (isBack && isTo || (!isBack && !isTo)) return `path[id^='${link.linkFrom}-${link.linkTo}']`;
            else if (isBack) return `path[id^='${link.linkFrom}-backto-${link.linkTo}']`;
            else return `path[id^='${link.linkFrom}-to-${link.linkTo}']`;
          })();
          //const selector = `path[id^='${link.linkFrom}'][id$='${link.linkTo}']`
          const linkPath = svg.querySelectorAll(selector)[0];
          let linkTitle = svg.querySelectorAll(`a[href="http://#${encodeURI(linkId)}"]`);
          if (linkPath) {
            for (let i = 0; i < linkTitle.length; i++)
              linkTitle[i].remove();
            linkPath.classList.add('link-path');
            linkPath.style = null;
            const defPathID = `def_${prefix++}_${linkPath.id}`;
            const path = this.createSVGElement('svg:path');
            path.setAttribute('id', defPathID);
            path.setAttribute('d', linkPath.getAttribute('d'));
            defs.appendChild(path);

            linkTitle = this.createSVGElement('svg:text');
            linkTitle.setAttribute('dy', -4);
            linkTitle.setAttribute('text-anchor', 'middle');

            const titlePath = this.createSVGElement('svg:textPath');
            titlePath.setAttribute('href', `#${defPathID}`);
            titlePath.setAttribute('startOffset', '50%');
            titlePath.textContent = link.link_title;

            linkTitle.setAttribute('data-link-selector', prefix);
            titlePath.setAttribute('data-link-selector', prefix);
            titlePath.addEventListener('mouseover', this.onOverLink);
            titlePath.addEventListener('mouseout', this.onOutLink);
            titlePath.addEventListener('mousedown', this.onSelected);

            linkPath.setAttribute('data-link-selector', prefix);
            linkPath.addEventListener('mouseover', this.onOverLink);
            linkPath.addEventListener('mouseout', this.onOutLink);
            linkPath.addEventListener('mousedown', this.onSelected);

            linkTitle.appendChild(titlePath);
            svg.appendChild(linkTitle);
          } else if (linkTitle.length) {
            const oldLinks = linkTitle;
            linkTitle = linkTitle[0].querySelectorAll('text')[0];
            for (let i = 0; i < oldLinks.length; i++)
              oldLinks[i].remove();
            if (linkTitle.innerHTML !== '⠀')
              svg.appendChild(linkTitle);
          } else if (!linkTitle.length) {
            linkTitle = undefined;
          }

          if (!linkTitle) continue;

          linkTitle.classList.add('schema-link-title');

          if (link.contract) {
            const contactID = link.contract.id;
            linkTitle.style.cursor = 'pointer';
            linkTitle.addEventListener('click', () => {
              if (uri.isExternalURI(contactID))
                window.open(contactID, '_blank');
              else
                this.$router.push({ path: `/docs/${contactID}` });
            });
          }

        }
      },
      postRenderSmetana(svg) {
        const links = svg.querySelectorAll('path');
        for (let i = 0; i < links.length; i++) {
          const linkPath = links[i];
          linkPath.classList.add('link-path');
          linkPath.addEventListener('mouseover', this.onOverLink);
          linkPath.addEventListener('mouseout', this.onOutLink);
        }

        for (const linkId in this.structure.links) {
          const link = this.structure.links[linkId];
          const linkTitle = svg.querySelectorAll(`a[href="http://#${encodeURI(linkId)}"]`)[0];
          if (!link || !linkTitle) continue;
          linkTitle.setAttribute('title', '');
          if (link.contract) {
            const contactID = link.contract.id;
            const url = uri.isExternalURI(contactID) ? contactID : `/docs/${contactID}`;
            linkTitle.setAttribute('xlink:title', url);
            linkTitle.setAttribute('href', url);
          } else if (linkTitle) {
            linkTitle.setAttribute('xlink:title', '');
            linkTitle.setAttribute('href', '');
          }
        }
      },

      postrender(svg) {
        switch (this.renderCore) {
          case 'smetana': this.postRenderSmetana(svg); break;
          default: this.postRenderDot(svg);
        }
      },
      makeRef(type, id, title) {
        const url = (() => {
          switch (type) {
            case 'context':
              return (new URL(`architect/contexts/${id}`, location.origin)).toString();
            case 'component':
              return (new URL(`architect/components/${id}`, location.origin)).toString();
            case 'aspect':
              return (new URL(`architect/aspects/${id}`, location.origin)).toString();
            case 'contract':
              return (new URL(`docs/${id}`, location.origin)).toString();
          }
        })();
        return `[[${url} ${title || id}]]`;
      }
    }
  };
</script>

<style>
.schema-link-title {
  font-size: 12px;
  margin-bottom: 6px;
}

text.hover {
  font-size: 16px;
  cursor: pointer;
}

path.link-path {
  /* stroke: rgb(52, 149, 219) !important; */
  stroke-width: 2 !important;
}

path.hover,
path.selected {
  stroke: #F00 !important;
  stroke-width: 2 !important;
}
</style>
