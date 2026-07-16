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
      R.Piontik <r.piontik@mail.ru> - 2023
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
-->

<template>
  <div class="image-cont" v-bind:class="{ 'drag-active': isLMBDragActive }">
    <v-alert v-if="error" color="warning">
      Здесь должна быть картинка, но что-то пошло не так.<br>
      Проверьте, что ресурс доступен, а CORS политики настроены верно.<br>
      URL: {{ url.toString() }}<br>
      Ошибка: {{ error }}
    </v-alert>
    <img v-else ref="imgEle" v-bind:alt="alt" v-bind:src="data" v-bind:style="!isFullScreen && 'max-width:100%'">
    <div v-if="availableFullscreen" class="fullscreen-icon">
      <v-icon class="icon-fullscreen" v-on:click="toggleFullscreen">
        {{ isFullScreen ? 'mdi-close-box-outline' : 'mdi-fullscreen' }}
      </v-icon>
    </div>
  </div>
</template>

<script>
  import requests from '@front/helpers/requests';
  import uriTool from '@front/helpers/uri';
  import fullScreen from '@front/helpers/fullscreen';

  export default {
    name: 'DHImage',
    props: {
      src: { type: String, default: '' },
      baseURI: { type: String, default: '' },
      alt: { type: String, default: '' }
    },
    data() {
      return {
        error: null,
        data: null,
        isFullScreen: false,
        isDownscaled: false,
        resObserver: null,
        isLMBDragActive: false,
        dragStartX: 0,
        dragStartY: 0,
        dragStartScrollLeft: 0,
        dragStartScrollTop: 0,
        dragListenersAttached: false
      };
    },
    computed: {
      availableFullscreen() {
        return fullScreen.isAvailable() && this.isDownscaled || this.isFullScreen;
      },
      url() {
        return uriTool.makeURL(this.src, this.baseURI).url;
      }
    },
    watch: {
      isFullScreen(active) {
        if (active) {
          this.attachLMBDragListeners();
        } else {
          this.detachLMBDragListeners();
        }
      }
    },
    mounted() {
      this.reloadImage();
      this.observer = new ResizeObserver(this.handleResize);
      this.observer.observe(this.$refs.imgEle);
    },
    beforeUnmount() {
      this.observer?.disconnect();
      this.detachLMBDragListeners();
    },
    methods: {
      reloadImage() {
        requests.request(this.src, this.baseURI, { responseType: 'arraybuffer' })
          .then((response) => {
            this.data = URL.createObjectURL(new Blob([response.data], { type: response.headers['content-type']}));
          })
          .catch((e) => {
            this.error = e;
          });
      },
      handleResize(entries) {
        const img = entries[0].target;
        this.isDownscaled = img.naturalWidth > img.clientWidth;
      },
      toggleFullscreen() {
        fullScreen.toggle(this.$el, (value) => {
          this.isFullScreen = value;
        });
      },
      attachLMBDragListeners() {
        if (this.dragListenersAttached) return;

        this.$el.addEventListener('mousedown', this.onLMBMouseDown);
        window.addEventListener('mousemove', this.onLMBMouseMove);
        window.addEventListener('mouseup', this.onLMBMouseUp);
        this.dragListenersAttached = true;
      },
      detachLMBDragListeners() {
        this.$el.removeEventListener('mousedown', this.onLMBMouseDown);
        window.removeEventListener('mousemove', this.onLMBMouseMove);
        window.removeEventListener('mouseup', this.onLMBMouseUp);
        this.isLMBDragActive = false;
        this.dragListenersAttached = false;
      },
      onLMBMouseDown(event) {
        if (event.button !== 0 || !this.isFullScreen) return;

        event.preventDefault();
        this.isLMBDragActive = true;
        this.dragStartX = event.clientX;
        this.dragStartY = event.clientY;
        this.dragStartScrollLeft = this.$el.scrollLeft;
        this.dragStartScrollTop = this.$el.scrollTop;
      },
      onLMBMouseMove(event) {
        if (!this.isLMBDragActive) return;

        this.$el.scrollLeft = this.dragStartScrollLeft - (event.clientX - this.dragStartX);
        this.$el.scrollTop = this.dragStartScrollTop - (event.clientY - this.dragStartY);
      },
      onLMBMouseUp(event) {
        if (event.button !== 0) return;

        this.isLMBDragActive = false;
      }
    }
  };
</script>

<style scoped>
.image-cont {
  position: relative;
}

.icon-fullscreen {
  background: #fffe;
  border-radius: 20%;
}

.image-cont:hover > .fullscreen-icon {
  display:block;
}

.image-cont:fullscreen > .fullscreen-icon {
  position: fixed;
}

.image-cont:fullscreen {
  overflow: auto;
  display: flex;
  align-items: center;
  cursor: grab;
}

.image-cont:fullscreen.drag-active {
  cursor: grabbing;
}

.image-cont:fullscreen > img {
  max-width: unset;
  margin: auto;
}

</style>
