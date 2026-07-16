<!--
  Copyright (C) 2026 Sber

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.

  Maintainers:
      Temnyakov Nikolay <temnjakovn@gmail.com>, Sber

  Contributors:
      Temnyakov Nikolay <temnjakovn@gmail.com>, Sber - 2026
-->

<template>
  <transition name="modal">
    <div v-if="show" class="modal-mask" v-on:mousedown.self="closeModal">
      <div class="modal-wrapper">
        <div ref="modal" class="modal-container">
          <button class="modal-close" aria-label="button close" v-on:click="closeModal">
            <icon-inputs-close />
          </button>
          <div v-if="showHeader" class="modal-header">
            <slot name="header">default header</slot>
          </div>

          <div v-if="showDescription" class="modal-description">
            <slot name="description" />
          </div>

          <div v-if="showBody" class="modal-body">
            <slot name="body">default body</slot>
          </div>

          <div v-if="buttonLeft || buttonRight" class="modal-footer" v-bind:class="classBtnPosition">
            <button-upload
              v-if="buttonLeft"
              v-bind:color="'black'"
              v-bind:height="'lg'"
              class="modal-footer__button"
              v-on:click="clickButtonLeft">
              <template #button_text>
                <slot name="button_left" />
              </template>
              <template #button_icon>
                <slot name="button_left_icon" />
              </template>
            </button-upload>
            <button-upload
              v-if="buttonRight"
              v-bind:height="'lg'"
              class="modal-footer__button"
              v-bind:is-loading="isRightBtnLoading"
              v-on:click="clickButtonRight">
              <template #button_text>
                <slot name="button_right" />
              </template>
              <template #button_icon>
                <slot name="button_right_icon" />
              </template>
            </button-upload>
          </div>
        </div>
      </div>
    </div>
  </transition>
</template>

<script>
  import Button from './buttons/Button.vue';
  import IconInputsClose from './icons/inputs/IconInputsClose.vue';

  export default {
    name: 'ModalComponent',
    components: {
      'button-upload': Button,
      'icon-inputs-close': IconInputsClose
    },
    props: {
      show: {
        type: Boolean,
        default: false
      },
      btnPosition: {
        type: String,
        default: 'center',
        validator: (value) => ['left', 'right', 'center'].includes(value)
      },
      isRightBtnLoading: {
        type: Boolean,
        default: false
      }
    },
    data() {
      return {
        modal: null
      };
    },
    computed: {
      showHeader() {
        return !!this.$slots.header;
      },
      showDescription() {
        return !!this.$slots.description;
      },
      showBody() {
        return !!this.$slots.body;
      },
      buttonLeft() {
        return !!this.$slots.button_left;
      },
      buttonRight() {
        return !!this.$slots.button_right;
      },
      classBtnPosition() {
        return `modal-footer__button_${this.btnPosition}`;
      }
    },
    watch: {
      show(newVal) {
        document.body.style.overflowY = newVal ? 'hidden' : 'auto';
      }
    },
    methods: {
      clickButtonLeft() {
        this.$emit('buttonLeft');
      },
      clickButtonRight() {
        this.$emit('buttonRight');
      },
      closeModal() {
        this.$emit('close');
      }
    }
  };
</script>

<style scoped>
.modal-mask {
  position: fixed;
  z-index: 10;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  width: 100vw;
  height: 100vh;
  background: rgba(51, 51, 51, 0.8);
  display: flex;
  justify-content: center;
  align-content: center;
  align-items: center;
  overflow: hidden;
  transition: opacity 0.3s ease;
}

.modal-wrapper {
  display: table-cell;
  vertical-align: middle;
}

.modal-container {
  position: relative;
  width: fit-content;
  min-width: 500px;
  max-width: 80dvw;
  max-height: 90dvh;
  margin: 0 auto;
  padding: 32px;
  background-color: #f5f5f5;
  border-radius: 2px;
  box-shadow: 0px 4px 8px rgba(0, 0, 0, 0.04),
    0px 0px 2px rgba(0, 0, 0, 0.06),
    0px 0px 1px rgba(0, 0, 0, 0.04);
  transition: all 0.3s ease;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

.modal-close {
  position: absolute;
  top: 15px;
  right: 15px;
  display: flex;
  padding: 1px;
}

.modal-header {
  font-size: 24px;
  font-weight: bold;
  color: #000000;
  margin-bottom: 16px;
  flex-shrink: 0;
}

.modal-description {
  font-size: 14px;
  color: #535353;
  margin-bottom: 24px;
  flex-shrink: 0;
}

.modal-body {
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  align-items: center;
  overflow-y: auto;
  flex: 1 1 auto;
  min-height: 0;
  width: 100%;
  box-sizing: border-box;
}

.modal-footer {
  display: flex;
  margin-top: 24px;
  flex-shrink: 0;
}

.modal-footer__button_left {
  justify-content: left;
}

.modal-footer__button_right {
  justify-content: right;
}

.modal-footer__button_center {
  justify-content: center;
}

.modal-footer__button_center .modal-footer__button {
  width: 100%;
}

.modal-footer__button:not(:last-of-type) {
  margin-right: 20px;
}

.modal-fade-enter-active {
  transition: all 0.3s ease-out;
}

.modal-fade-leave-active {
  transition: all 0.8s cubic-bezier(1, 0.5, 0.8, 1);
}

.modal-leave-to,
.modal-enter-from {
  opacity: 0;
}

.modal-leave-to .modal-container,
.modal-enter-from .modal-container {
  transform: translateY(30px);
}
</style>
