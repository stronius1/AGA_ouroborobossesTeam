<!--
  Copyright (C) 2023 Sber

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
      Temnyakov Nikolay <temnjakovn@gmail.com>, Sber - 2025
-->

<template>
  <button
    class="button"
    aria-label="button"
    v-bind:class="classes"
    v-bind:type="type"
    v-bind:disabled="isLoading || isDisabled"
    v-on:click="$emit('click')">
    <loader v-if="isLoading" color="white" />
    <template v-else>
      <span v-if="buttonText" class="button__text">
        <slot name="button_text" />
      </span>
      <slot v-if="buttonIcon" name="button_icon" />
    </template>
  </button>
</template>

<script>
  import Loader from '../loading/Loader.vue';

  export default {
    name: 'Button',
    components: {
      Loader
    },
    props: {
      type: {
        type: String,
        default: 'button',
        validator: (prop) => ['button', 'submit', 'reset'].includes(prop)
      },
      color: {
        type: String,
        default: 'primary',
        validator: (prop) => ['primary', 'grey', 'black', 'outlined'].includes(prop)
      },
      height: {
        type: String,
        default: 'md',
        validator: (value) => ['sm', 'md', 'lg', 'auto'].includes(value)
      },
      isDisabled: {
        type: Boolean,
        default: false
      },
      isLoading: {
        type: Boolean,
        default: false
      },
      loaderProps: {
        type: Object,
        default: () => ({
          color: 'primary',
          size: 'xs'
        })
      }
    },
    computed: {
      classBtnColor() {
        return `button-color_${this.color}`;
      },
      classBtnHeight() {
        return `button-height_${this.height}`;
      },
      classLoading() {
        return this.isLoading ? 'button_loading' : '';
      },
      classes() {
        return [this.classBtnColor, this.classBtnHeight, this.classLoading];
      },
      buttonText() {
        return this.$slots.button_text;
      },
      buttonIcon() {
        return this.$slots.button_icon;
      }
    }
  };
</script>

<style>
/* CSS remains unchanged */
.button svg {
  display: flex;
  justify-content: center;
  align-items: center;
  transition: all 0.3s ease;
  margin-left: 10px;
}

.button-color_primary svg,
.button-color_black svg {
  fill: #ffffff;
  stroke: #ffffff;
}

.button-color_outlined svg {
  fill: #1ABB6E;
  stroke: #1ABB6E;
}

.button-color_outlined:active svg {
  fill: #117D49;
  stroke: #117D49;
}

@media (hover: hover) and (pointer: fine) {
  .button-color_outlined:hover svg {
    fill: #169C5C;
    stroke: #169C5C;
  }
}

.button {
  display: flex;
  justify-content: center;
  align-items: center;
  border: none;
  border-radius: 3px;
  cursor: pointer;
  transition: all 0.3s ease;
}

.button__text {
  display: flex;
  align-items: center;
  letter-spacing: 0.2px;
}

.button:not(.button_loading)[disabled] {
  color: #C2C2C2;
  background-color: #C2C2C2;
  cursor: not-allowed;
}

.button_loading {
  cursor: wait;
}

.button-color_primary {
  color: #ffffff;
  background-color: #40C686;
}

@media (hover: hover) and (pointer: fine) {
  .button-color_primary:hover {
    background-color: #1ABB6E;
  }
}

.button-color_primary:active {
  background-color: #169C5C;
}

.button-color_primary:not(.button_loading)[disabled] {
  color: #ffffff;
  background: #40C686;
  cursor: not-allowed;
  opacity: 0.5;
}

.button-color_outlined {
  color: #40C686;
  border: 1px solid #40C686;
}

@media (hover: hover) and (pointer: fine) {
  .button-color_outlined:hover {
    color: #1ABB6E;
    border: 1px solid #1ABB6E;
  }
}

.button-color_outlined:active {
  color: #169C5C;
  border: 1px solid #169C5C;
}

.button-color_black {
  color: #ffffff;
  background-color: #989898;
}

@media (hover: hover) and (pointer: fine) {
  .button-color_black:hover {
    background-color: #989898;
  }
}

.button-color_black:active {
  background: #989898;
}

.button-color_grey {
  color: #0D5E37;
  background-color: #ECECEC;
}

.button-color_grey:not(.button_loading)[disabled] {
  color: #ffffff;
  cursor: default;
  filter: opacity(50%);
}

@media (hover: hover) and (pointer: fine) {
  .button-color_grey:hover {
    color: #40C686;
  }
}

/* Высота кнопки */
.button-height_auto {
  height: auto;
}

.button-height_sm {
  height: 32px;
  padding: 5px 10px;
}

.button-height_md {
  height: 38px;
  padding: 8px 12px;
}

.button-height_lg {
  height: 48px;
  padding: 13px 18px;
}
</style>
