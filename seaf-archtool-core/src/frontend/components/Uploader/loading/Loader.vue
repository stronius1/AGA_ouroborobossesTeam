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
  <div class="lds-ellipsis" v-bind:class="classes">
    <div />
    <div />
    <div />
    <div />
  </div>
</template>

<script>
  export default {
    name: 'Loader',

    props: {
      color: {
        type: String,
        default: 'primary',
        validator(value) {
          return ['primary', 'white'].includes(value);
        }
      },
      size: {
        type: String,
        default: 'md',
        validator(value) {
          return ['xs', 'md', 'lg'].includes(value);
        }
      },
      isCenteredHorizontally: {
        type: Boolean,
        default: true
      }
    },

    computed: {
      classColor() {
        return `lds_color_${this.color}`;
      },
      classSize() {
        return `lds_size_${this.size}`;
      },
      classMargin() {
        return this.isCenteredHorizontally ? 'lds_margin' : '';
      },
      classes() {
        return [this.classColor, this.classSize, this.classMargin].filter(Boolean);
      }
    }
  };
</script>

<style scoped>
.lds_margin {
  margin: 0 auto;
}

.lds_size_xs {
  height: 30px;
}

.lds_size_xs div {
  width: 10px;
  height: 10px;
}

.lds_size_md {
  height: 40px;
}

.lds_size_md div {
  width: 13px;
  height: 13px;
}

.lds_size_lg {
  height: 80px;
}

.lds_size_lg div {
  width: 20px;
  height: 20px;
}

.lds_color_primary div {
  background: #0F62FE;
}

.lds_color_white div {
  background: #ffffff;
}

.lds-ellipsis {
  display: flex;
  position: relative;
  width: 80px;
  background-color: transparent;
}

.lds-ellipsis div {
  position: absolute;
  top: 40%;
  border-radius: 50%;
  will-change: transform;
  animation-timing-function: cubic-bezier(0, 1, 1, 0);
}

.lds-ellipsis div:nth-child(1) {
  left: 8px;
  animation: lds-ellipsis1 0.6s infinite;
}

.lds-ellipsis div:nth-child(2) {
  left: 8px;
  animation: lds-ellipsis2 0.6s infinite;
}

.lds-ellipsis div:nth-child(3) {
  left: 32px;
  animation: lds-ellipsis2 0.6s infinite;
}

.lds-ellipsis div:nth-child(4) {
  left: 56px;
  animation: lds-ellipsis3 0.6s infinite;
}

@keyframes lds-ellipsis1 {
  0% {
    transform: scale(0);
  }

  100% {
    transform: scale(1);
  }
}

@keyframes lds-ellipsis3 {
  0% {
    transform: scale(1);
  }

  100% {
    transform: scale(0);
  }
}

@keyframes lds-ellipsis2 {
  0% {
    transform: translate(0, 0);
  }

  100% {
    transform: translate(24px, 0);
  }
}
</style>
