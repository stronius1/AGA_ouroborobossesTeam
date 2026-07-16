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
      R.Piontik <r.piontik@mail.ru> - 2024
      Vladislav Nefedov <clay.zenx@gmail.com>, Sber - 2024
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2025
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
-->

<template>
  <box
    class="space"
    v-bind:errors="errors"
    v-bind:path="path"
    v-on:doc-contextmenu="showContextMenu">
    <context-menu v-model="menu.show" v-bind:x="menu.x" v-bind:y="menu.y" v-bind:items="contextMenu" />
    <dochub-anchor id="" />
    <final-markdown
      v-if="showDocument"
      v-bind:template="outHTML"
      v-bind:base-u-r-i="currentURL"
      v-on:go-markdown="onGoMarkdown" />
    <spinner v-else />
  </box>
</template>

<script>
  import MarkdownIt from 'markdown-it';
  import mustache from 'mustache';
  import Prism from 'prismjs';
  import { createVNode, render } from 'vue';

  import requests from '@front/helpers/requests';
  import href from '@front/helpers/href';
  import uri from '@front/helpers/uri';

  import { DocTypes } from '@front/components/Docs/enums/doc-types.enum';
  import DocMarkdownObject from './DocHubObject';
  import DocMixin from './DocMixin';
  import ContextMenu from './DocContextMenu.vue';
  import Spinner from '@front/components/Controls/Spinner.vue';
  import env from '@front/helpers/env';
  import sanitizeUrl from '@global/helpers/sanitizeUrl.mjs';
  import {extractFrontmatter} from '@global/manifest/tools/yamlHeader.mjs';
  import {pageEventRegDoc, waitNextDoc} from '@front/clickstream/pageEvent.ts';
  import consts from '@front/consts.js';
  import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
  import CopyButton from '@front/components/Buttons/CopyButton.vue';

  const logger = getLoggerWithTag('f/c/D/DocMarkdown');

  export default {
    name: 'DocMarkdown',
    components: {
      ContextMenu,
      Spinner,
      finalMarkdown: {
        props: {
          template: { type: String, default: '' },
          baseURI: { type: String, default: '' }
        },
        emits: ['go-markdown'],
        computed: {
          compiledMarkdown() {
            const parent = this;
            return {
              name: 'FinalMarkdownContent',
              components: {
                'dochub-object': DocMarkdownObject
              },
              data() {
                return {
                  baseURI: parent.baseURI
                };
              },
              template: `<div class="markdown-document">${this.template}</div>`
            };
          }
        },
        methods: {
          goToMarkdown(event) {
            this.$emit('go-markdown', event);
            return false;
          },
          goToAnchor(event) {
            const id = event.target.attributes.href.value.slice(1);
            const element = document.getElementById(id);
            element?.scrollIntoView();
          },
          // Ищем ссылки на markdown документы для переходов по ним
          sniffMarkdownLinks(el) {
            const refs = el?.querySelectorAll && el.querySelectorAll('[href]') || [];
            for (let i = 0; i < refs.length; i++) {
              const refItem = refs[i];
              if (refItem.href.slice(-3) === '.md') {
                refItem.onclick = this.goToMarkdown;
              } else if (refItem?.attributes?.href?.value?.startsWith('#')) {
                refItem.onclick = this.goToAnchor;
              }
            }
          },
          createCopyButton(el) {
            const codeElements = el.getElementsByTagName('code');

            for (let i = 0; i < codeElements.length; i++) {
              const codeElement = codeElements[i];
              const preElement = codeElement.parentElement;

              if (preElement && preElement.tagName === 'PRE') {
                // не добавляем кнопку если:
                // - она уже есть, т.е. есть класс code-copy-button
                // - это markuper
                if (preElement.querySelector(
                  '.code-copy-button, .language-markuper-form-label, .language-markuper-form-field'
                )) continue;

                const buttonContainer = document.createElement('div');
                buttonContainer.className = 'code-copy-button';

                const copyButtonVNode = createVNode(CopyButton, {
                  getCopiedText: () => codeElement.textContent
                });
                copyButtonVNode.appContext = this.$.appContext;

                render(copyButtonVNode, buttonContainer);
                preElement.insertBefore(buttonContainer, codeElement);
              }
            }
          }
        },
        mounted() {
          href.elProcessing(this.$el);
          this.sniffMarkdownLinks(this.$el);
          this.createCopyButton(this.$el);
        },
        template: '<component v-bind:is="compiledMarkdown" />'
      }
    },
    mixins: [DocMixin],
    props: {
      tocShow: {
        type: Boolean,
        default: true
      },
      inline: {
        type: Boolean,
        default: true
      }
    },
    data() {
      return {
        showDocument: false,
        toc: '',
        markdown: null,
        outHTML: null,
        redirectURL: null
      };
    },
    computed: {
      // Определяет поддерживаются ли HTML тэги в markdown
      isHTMLSupport() {
        return (process.env.VUE_APP_DOCHUB_MARKDOWN_HTML || env.ideSettings?.env.DOCHUB_IDE_MARKDOWN_HTML || 'off').toLocaleLowerCase() === 'on';
      },
      // Возвращает URL документа с учетом истории переходов
      currentURL() {
        return this.redirectURL ? this.redirectURL : this.url;
      },
      // Доступные типы документов
      availableDocTypes() {
        const result = [];
        for (const key in DocTypes) result.push(DocTypes[key].toLowerCase());
        const extended = this.$store.state.plugins.documents;
        for (const key in extended) result.push(key.toLowerCase());
        return result;
      }
    },
    methods: {
      createMarkdownRenderer() {
        const renderer = new MarkdownIt({
          html: this.isHTMLSupport,
          breaks: false,
          linkify: false,
          highlight: (content, language) => this.highlightCode(content, language)
        });

        const defaultFenceRenderer = renderer.renderer.rules.fence;
        renderer.renderer.rules.fence = (tokens, idx, options, env, slf) => {
          const token = tokens[idx];
          const language = (token.info || '').trim().split(/\s+/)[0];
          const rendered = defaultFenceRenderer(tokens, idx, options, env, slf);

          if (!language) return rendered;

          const languageClass = `${options.langPrefix}${renderer.utils.escapeHtml(language)}`;
          return rendered.replace('<pre>', `<pre class="${languageClass}">`);
        };

        return renderer;
      },
      highlightCode(content, language) {
        const normalizedLanguage = (language || '').trim().split(/\s+/)[0].toLowerCase();
        const prismLanguage = normalizedLanguage === 'yml' ? 'yaml' : normalizedLanguage;
        const grammar = Prism.languages[prismLanguage];

        if (!grammar) return '';

        return Prism.highlight(content, grammar, prismLanguage);
      },
      createSlug(text) {
        return text
          .toString()
          .trim()
          .toLowerCase()
          .replace(/[^\w\u0400-\u04FF\s-]/g, '')
          .replace(/\s+/g, '-');
      },

      renderMarkdownContent(content) {
        const renderer = this.createMarkdownRenderer();
        const tokens = renderer.parse(content, {});
        const tocItems = [];

        tokens.forEach((token, index) => {
          if (token.type !== 'heading_open') return;

          const nextToken = tokens[index + 1];
          const title = nextToken?.children?.length
            ? nextToken.children.map((child) => child.content).join('')
            : nextToken?.content || '';
          const level = Number(token.tag.slice(1));
          const id = this.createSlug(title);

          token.attrSet('id', id);
          tocItems.push({ id, level, title: renderer.utils.escapeHtml(title) });
        });

        this.tocRendered(this.renderTOC(tocItems));
        return renderer.renderer.render(tokens, renderer.options, {});
      },
      renderTOC(items) {
        if (!items.length) return '';

        const result = [];
        const baseLevel = items[0].level;
        let currentLevel = baseLevel;
        let isFirstItem = true;

        result.push('<ul class="table-of-contents">');

        for (const item of items) {
          if (item.level > currentLevel) {
            while (currentLevel < item.level) {
              result.push('<ul>');
              currentLevel += 1;
            }
          }
          else if (item.level < currentLevel) {
            while (currentLevel > item.level) {
              result.push('</li></ul>');
              currentLevel -= 1;
            }
            result.push('</li>');
          }
          else if (!isFirstItem) {
            result.push('</li>');
          }

          result.push(
            `<li class="toc-level-${item.level}"><a href="#${item.id}">${item.title}</a>`
          );

          isFirstItem = false;
        }

        while (currentLevel > baseLevel) {
          result.push('</li></ul>');
          currentLevel -= 1;
        }

        result.push('</li></ul>');

        return result.join('');
      },
      onGoMarkdown(event) {
        const ref = event.target.attributes.href.nodeValue;
        const route = Object.assign({}, this.$router.currentRoute);
        const query = Object.assign({}, this.$router.currentRoute.query);
        query.redirect =  uri.makeURIByBaseURI(ref, this.currentURL);
        logger.info(() => route.query);
        this.$router.push({
          params: route.query,
          query
        });
        return false;
      },
      rendered(outHtml) {
        let docCount = 0; // счетчик количества сработавших replace, нужен ниже
        // Парсим ссылки на объекты DocHub
        let result = outHtml.replace(/<img\s+([^>]*?)>/g, (segment, attrs) => {
          docCount++;
          return '<dochub-object :baseURI="baseURI" :inline="true" ' + attrs + '></dochub-object>';
        })
          .replace(/\{\{/g, '<span v-pre>{{</span>')
          .replace(/\}\}/g, '<span v-pre>}}</span>');
        // если replace сработал хоть 1 раз, значит будет подгрузка вложенных документов
        // и надо подождать их перед отправкой события загрузки страница
        if (docCount > 0) {
          waitNextDoc(consts.clickstream.MARKDOWN_WAIT_SUBDOC_RENDER_MS);
        }
        // Заменяем [[toc]] на содержимое TOC, если оно присутствует
        result = this.insertTOCIfNeeded(result);

        if (this.outHTML != result) {
          this.showDocument = false;
          this.outHTML = result;
          this.$nextTick(() => {
            this.showDocument = true;
            setTimeout(() => {
              this.loadState();

              if (!window.location.hash) return;

              const url = sanitizeUrl(window.location.href);
              const anchorId = decodeURIComponent(url.hash.slice(1));

              if (!anchorId) return;

              const anchorElement = document.getElementById(anchorId);
              anchorElement?.scrollIntoView();
            }, 50);
          });
        }
        return '';
      },
      insertTOCIfNeeded(result) {
        if (!this.toc) {
          return result;
        }

        const replaced = result.replace(/\[\[toc]]/, `<div class="toc">${this.toc}</div>`);
        // если замена произошла, значит пользователь добавить плейсхолдер [[toc]] и мы на это место добавили оглавление
        if (replaced !== result) {
          return replaced;
        }

        // Если пользователь не вставил [[toc]], добавим в начало
        return `<div class="toc">${this.toc}</div>\n\n` + result;
      },
      /**
       * callback для библиотеки markdown. Сюда приходит отрендеренный toc в виде html
       * @param tocHTML - html содержащий toc
       */
      tocRendered(tocHTML) {
        // если явно указано, что toc не нужен в документе или во вложении, тогда не сохраняем его
        if (this.profile?.toc === false || this.inline || !this.tocShow) {
          this.toc = null;
          return;
        }
        if (this.profile?.toc !== true) {
          // Считаем количество заголовков только если пользователь явно не указал, что toc нужен
          // т.е. если нет toc или он не равен true
          // т.к. это оглавление, и считать пункты li не получается (они вложенные их много), проще посчитать ссылки
          const listItemsCount = (tocHTML.match(/<a href\b[^>]*>/gi) || []).length;

          if (listItemsCount <= 3) {
            this.toc = null;
            return;
          }
        }
        this.toc = tocHTML;
      },
      prepareMarkdown(content) {
        // Преобразуем встроенный код в объекты документов
        return content.replace(/```(\w\w*)(\n|\r)([^`]*)```/gim, (segment, language, br, content) => {
          if (this.availableDocTypes.indexOf(language.toLowerCase()) < 0 ) return segment;
          // eslint-disable-next-line no-debugger
          const urlObject = URL.createObjectURL(new Blob([content], { type: `text/${language};charset=UTF-8` }));
          return `![](@document/${urlObject})`;
        });
      },
      refresh() {
        // Если есть параметр перенаправления, используем его
        this.redirectURL = this.$router.currentRoute?.query?.redirect;

        // Обновляем документ
        this.markdown = null;
        if (!this.currentURL) return;
        this.outHTML = null;
        this.showDocument = false;
        this.toc = '';
        pageEventRegDoc();
        this.sourceRefresh().then(() => {
          requests.request(this.currentURL).then(({ data }) => {
            let content = null;
            this.error = null;
            if (!data)
              content = 'Здесь пусто :(';
            else if (this.isTemplate) {
              content = mustache.render(data, this.source.dataset);
            } else {
              content = data;
            }
            // Извлекаем документ отделяя от метаданных если они есть
            content = extractFrontmatter(content).content;
            this.markdown = this.prepareMarkdown(content);
            this.rendered(this.renderMarkdownContent(this.markdown));
          }).catch((e) => {
            this.error = e;
          });
        });
      }
    }
  };
</script>

<!--todo: ERA-1329: создание toc работает в любом месте, но по какой-то причине вылетает ошибка
          vue-router.esm.js:2046 Uncaught (in promise) NavigationDuplicated: Avoided redundant navigation to current location: "/entities/docs/blank?dh-doc-id=seaf.no-toc".
          так же при скролле выбранный заголовок прячется за шапкой, надо править-->
<style>
.table-of-contents {
  list-style-type: circle;
  padding-left: 24px;
}

.table-of-contents ul {
  list-style-type: square;
}

.theme--light.v-application code {
  background: none !important;
}

.dochub-object {
  margin-top: 12px;
  margin-bottom: 24px;
}
.space {
  padding: 24px;
  position: relative;
  /* min-height: 100vh; */
  min-height: 60px;
}

.toc {
  margin-bottom: 24px;
}

.toc a,
.markdown-document a {
  color: #1976d2;
}

.markdown-document {
  font-size: 1rem;
  line-height: 1.5rem;
}

.markdown-document pre {
  display: block;
  padding: 9.5px;
  margin: 0 0 10px;
  font-size: 13px;
  line-height: 1.42857143;
  color: #333;
  word-break: break-all;
  word-wrap: break-word;
  background-color: #f5f5f5;
  border: 1px solid #ccc;
  border-radius: 4px;
  overflow: auto;

  @media print {
    print-color-adjust: exact;
  }
}

.markdown-document .language-markuper-form-label {
  padding: 0 !important;
  color: #0009 !important;
  margin-bottom: 0 !important;
}

.markdown-document code[class*="language-"]:first-child {
  margin-left: -12px;
}

.markdown-document code[class*="language-"],
.markdown-document pre[class*="language-"] {
  padding: 16px 13px;
  color: black;
  font-weight: 300;
  background: none;
  text-shadow: 0 1px white;
  font-family: Consolas, Monaco, 'Andale Mono', 'Ubuntu Mono', monospace;
  text-align: left;
  white-space: pre-wrap;
  word-spacing: normal;
  word-break: normal;
  word-wrap: normal;
  line-height: 1.5;
  -moz-tab-size: 4;
  -o-tab-size: 4;
  tab-size: 4;
  -webkit-hyphens: none;
  -moz-hyphens: none;
  -ms-hyphens: none;
  hyphens: none;
  font-size: 13px;
  border-radius: 0;
}
.toc-anchor {
  display: none;
}
.markdown-document code[class*="language-"]::before, pre[class*="language-"]::before,
.markdown-document code[class*="language-"]::after, pre[class*="language-"]::after
{
  content: none !important;
}
.markdown-document table {
  border: solid #ccc 1px;
}
.markdown-document table.table td {
  padding-left: 6px;
  padding-right: 6px;
}
.markdown-document table thead th * {
  color: #fff !important;
}
.markdown-document table thead th  {
  background: #00755D;
  color: #fff !important;
  height: 40px;
}
.markdown-document table.table thead th {
  padding: 6px;
}
.markdown-document h1 {
  font-size: 1.5rem;
  margin-bottom: 18px;
  margin-bottom: 24px;
  clear:both;
}

.markdown-document h2 {
  margin-bottom: 18px;
  font-size: 1.25rem;
  clear:both;
}

.markdown-document h1:not(:first-child),
.markdown-document h2:not(:first-child) {
  margin-top: 56px;
}

.markdown-document h3,
.markdown-document h4,
.markdown-document h5 {
  margin-bottom: 18px;
  font-size: 1.125rem;
  clear:both;
}

.markdown-document h3:not(:first-child),
.markdown-document h4:not(:first-child),
.markdown-document h5:not(:first-child) {
  margin-top: 32px;
}

.markdown-document code[class*="language-"]{
  font-family: Menlo,Monaco,Consolas,Courier New,Courier,monospace;
  line-height: 22.4px;
  /* margin: 16px 13px; */
  font-size: 14px;
  border-radius: 8px;
}

.markdown-document code[class*="language-"] .token{
  background: none;
}

.markdown-document pre[class*="language-"]{
  border-radius: 4px;
  border: none;
  background-color: #eee;
}

.markdown-document pre[class*="language-mustache"] .token.variable{
  color: #cd880c;
}

/*noinspection CssUnusedSymbol*/
.code-copy-button {
  float: right;
}

blockquote {
  padding: 10px 20px;
  margin: 0 0 20px;
  border-left: 5px solid #eee;
}
</style>
