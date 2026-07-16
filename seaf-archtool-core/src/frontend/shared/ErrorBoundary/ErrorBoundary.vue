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
      R.Piontik <r.piontik@mail.ru> - 2023
      Artyom Prilip <artyom.prilip@gmail.com>, Sber - 2026
-->

<script>
  import { Comment, h } from 'vue';
  import { warn } from '@front/helpers/misc';
  import { errorMiddleware } from '@front/helpers/http';
  import errConstants from '@front/constants/errConstants.json';

  import DefaultFallback from './DefaultFallback.vue';

  export default {
    name: 'ErrorBoundary',
    props: {
      fallBack: {
        type: Object,
        default: () => DefaultFallback
      },
      onError: {
        type: Function,
        default: null
      },
      params: {
        type: Object,
        default: () => ({})
      },
      stopPropagation: {
        type: Boolean,
        default: false
      },
      tag: {
        type: String,
        default: 'div'
      }
    },
    emits: ['errorCaptured'],
    data() {
      return {
        err: '',
        info: '',
        hasError: null
      };
    },
    errorCaptured(err, vm, info = '') {
      this.hasError = true;
      this.err = err;
      this.info = info;
      this.$emit('errorCaptured', { err, vm, info });

      if (this.onError) {
        this.onError(err, vm, info);
      }

      if (this.stopPropagation) {
        return false;
      }
    },
    render() {
      const content = this.$slots.default?.();
      const boundarySlot = this.$slots.boundary;
      const hasRenderableNodes = (nodes) => Array.isArray(nodes) && nodes.some((node) => node.type !== Comment);

      let scopedSlot;

      if (boundarySlot) {
        scopedSlot = boundarySlot({
          hasError: this.hasError,
          err: this.err,
          info: this.info
        });
      }

      const fallbackOrScoped = boundarySlot
        ? scopedSlot
        : h(this.fallBack, errorMiddleware(this.params));

      if (this.hasError || this.params.error) {
        return Array.isArray(fallbackOrScoped)
          ? h(this.tag, null, fallbackOrScoped)
          : fallbackOrScoped;
      }

      if (boundarySlot) {
        if (!hasRenderableNodes(scopedSlot)) {
          return warn(errConstants.CHILD_EL_IS_NULL);
        }

        return Array.isArray(scopedSlot)
          ? h(this.tag, null, scopedSlot)
          : scopedSlot;
      }

      if (!hasRenderableNodes(content)) {
        return warn(errConstants.CHILD_EL_IS_NULL);
      }

      return Array.isArray(content)
        ? h(this.tag, null, content)
        : content;
    }
  };
</script>
