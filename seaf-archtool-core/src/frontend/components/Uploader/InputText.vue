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
      Temnyakov Nikolay <temnjakovn@gmail.com>, Sber - 2025
-->

<template>
  <div class="input" v-bind:class="{ isDisabled }">
    <input
      class="input__text"
      v-bind:class="{
        input__error_color: textError || (text && checkMinMaxNumber),
        'input_background-grey': colorGrey,
      }"
      v-bind:type="type"
      v-bind:value="text"
      v-bind:maxlength="maxLength"
      v-on:input="onInput"
      v-on:keydown.stop
      v-on:keypress.stop
      v-on:keyup.enter="$event.currentTarget.blur()">
    <span class="input__placeholder">
      <slot>Введите текст</slot>
    </span>

    <transition name="fade" mode="out-in">
      <div v-if="textError" class="input__error">
        {{ textError }}
      </div>
      <div v-else-if="String(text)" class="input__error">
        {{ checkMinMaxNumber }}
      </div>
    </transition>
  </div>
</template>

<script>
  export default {
    name: 'InputText',
    props: {
      type: {
        type: String,
        default: 'text',
        validator: prop => ['number', 'text', 'email', 'tel', 'password'].includes(prop)
      },
      minNumber: {
        type: Number
      },
      maxNumber: {
        type: Number
      },
      maxLength: {
        type: Number,
        default: 200
      },
      textError: {
        type: String,
        default: ''
      },
      colorGrey: {
        type: Boolean,
        default: false
      },
      text: {
        type: String,
        default: ''
      }
    },

    data() {
      return {
        isDisabled: false,
        ERROR_MAX_NUMBER: 'Число больше максимального значения',
        ERROR_MIN_NUMBER: 'Число меньше минимального значения'
      };
    },

    computed: {
      checkMinMaxNumber() {
        if (this.type !== 'number') return '';

        const number = Number(this.text);

        if (this.maxNumber != null && number > this.maxNumber) {
          return this.ERROR_MAX_NUMBER;
        }
        if (this.minNumber != null && number < this.minNumber) {
          return this.ERROR_MIN_NUMBER;
        }
        return '';
      }
    },

    methods: {
      onInput(event) {
        const value = String(event.target.value ?? '').slice(0, this.maxLength);
        this.$emit('inputText', value);
      }
    }
  };
</script>

<style scoped>
.input {
  position: relative;
  width: 100%;
  min-height: 38px;
}

.input__text {
  width: 100%;
  height: 38px;
  border: none;
  border-radius: 2px 2px 0 0;
  background-color: #ffffff;
  box-shadow: inset 0px -1px #535353;
  padding: 0 33px 0 10px;
  color: #333333;
  -webkit-appearance: none;
  appearance: none;
  transition: all 0.3s ease;
}

.input__text:focus,
.input__text:not(:focus):valid {
  padding: 10px 33px 0 10px;
}

.input__text:focus ~ .input__placeholder,
.input__text:not(:focus):valid ~ .input__placeholder {
  top: 0;
  left: 10px;
  font-size: 12px;
}

.input__placeholder {
  position: absolute;
  pointer-events: none;
  left: 10px;
  top: 10px;
  transition: all 0.3s ease;
  color: #989898;
}

.input__error {
  font-size: 12px;
  color: #d94236;
}

.input__error_color {
  background-color: #fbeced;
}

.input_background-grey {
  background-color: #f5f5f5;
}

.isDisabled {
  pointer-events: none;
}

.isDisabled .input__text {
  background-color: #fafafa;
  box-shadow: inset 0px -1px #c2c2c2;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
