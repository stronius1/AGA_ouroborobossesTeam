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
  <div />
</template>

<script>
  import { markRaw } from 'vue';
  import * as monaco from 'monaco-editor';
  import env from '@front/helpers/env';

  monaco.languages.register({id: 'jsonata'});
  monaco.languages.setMonarchTokensProvider('jsonata', {
    keywords: ['function'],
    functions: ['$spread'],
    special: env.isBackendMode ? [] : ['$log('],
    tokenizer: {
      root: [
        [/@?\$[a-zA-Z][\w$]*\(/, {
          cases: {
            '@special': 'special'
          }
        }],
        [/@?[a-zA-Z][\w$]*/, {
          cases: {
            '@keywords': 'keyword',
            '@default': 'data'
          }
        }],
        [/@?\$[a-zA-Z][\w$]*/, 'variable'],
        [/".*?"/, 'string'],
        [/\/\*(.|\W)*?\*\//, 'comment']
      ]
    }
  });

  monaco.editor.defineTheme('jsonata-theme', {
    base: 'vs',
    rules: [
      { token : 'comment', foreground: '#008000' },
      { token: 'keyword', foreground: '#000000', fontStyle: 'bold' },
      { token: 'special', foreground: '#ff0000', fontStyle: 'bold' },
      { token: 'variable', foreground: '#2233ee' },
      { token: 'function', foreground: '#2233ee', fontStyle: 'bold'},
      { token : 'string', foreground: '#990055' }
    ],
    colors: {
      'editor.foreground': '#000000'
    }
  });
  monaco.editor.setTheme('jsonata-theme');

  // https://ohdarling88.medium.com/4-steps-to-add-custom-language-support-to-monaco-editor-5075eafa156d
  // https://blog.expo.dev/building-a-code-editor-with-monaco-f84b3a06deaf
  export default {
    name: 'JSONataEditor',
    props: {
      modelValue: {
        type: String,
        default: ''
      }
    },
    emits: ['update:modelValue'],
    data() {
      return {
        model: null,
        editor: null,
        currentValue: '',
        isApplyingExternalValue: false
      };
    },
    watch: {
      modelValue(value) {
        const nextValue = value ?? '';
        if (nextValue === this.currentValue) return;

        this.setValue(nextValue);
      }
    },
    mounted() {
      this.currentValue = this.modelValue ?? '';

      this.editor = markRaw(monaco.editor.create(this.$el, {
        value: this.currentValue,
        language: 'jsonata',
        automaticLayout: true,
        minimap: {
          enabled: false
        },
        scrollBeyondLastLine: false
      }));

      this.model = this.editor.getModel();

      this.model.onDidChangeContent((event) => {
        if (this.isApplyingExternalValue) return;

        this.currentValue = this.applyModelChanges(this.currentValue, event.changes);
        this.$emit('update:modelValue', this.currentValue);
      });

      this.editor.addAction({
        id: 'custom.select-all',
        label: 'Select All',
        contextMenuGroupId: 'navigation',
        run: function(editor) {
          const range = editor.getModel().getFullModelRange();
          editor.setSelection(range);
        }
      });
    },
    unmounted() {
      this.editor.dispose();
      this.model.dispose();
    },
    methods: {
      applyModelChanges(value, changes) {
        return [...changes]
          .sort((a, b) => b.rangeOffset - a.rangeOffset)
          .reduce((result, change) => {
            return result.slice(0, change.rangeOffset)
              + change.text
              + result.slice(change.rangeOffset + change.rangeLength);
          }, value);
      },
      setValue(value) {
        const nextValue = value || '';
        this.currentValue = nextValue;

        if (!this.editor) return;

        this.isApplyingExternalValue = true;
        this.editor.setValue(nextValue);
        this.isApplyingExternalValue = false;
      },
      layout() {
        this.editor?.layout?.();
      }
    }
  };
</script>
