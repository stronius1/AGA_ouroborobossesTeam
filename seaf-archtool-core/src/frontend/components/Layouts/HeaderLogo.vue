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
      Rostislav Kabalin <kabalin2009@yandex.ru>

  Contributors:
      Rostislav Kabalin <kabalin2009@yandex.ru> - 2022
      Vladislav Nefedov <clay.zenx@gmail.com>, Sber - 2024
-->

<template>
  <div v-bind:class="$style.logo">
    <svg id="seaf" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 24 24">
      <g transform="scale(0.13) translate(-170,-91)">
        <g>
          <path fill="currentColor" d="M272.59,196.3l-.08-48.83,29.26,24.69,0,25a9.66,9.66,0,1,0,7.71.05l0-28.6-44.69-37.72.09,58.93L251.49,178.5l.15,93.79h7.71l-.13-77.16,5.67,4.77.11,72.38,63.1-.1,0-29.06Zm36.94,10.08a3.92,3.92,0,0,1-7.7.57,3.82,3.82,0,0,1-.13-.95,3.69,3.69,0,0,1,.13-.95,3.92,3.92,0,0,1,7.7.53Zm10.85,58.09-47.68.08-.1-58.15,47.76,40.3Z" />
        </g>
        <g>
          <path fill="currentColor" d="M255.21,92a9.64,9.64,0,0,0-3.83,18.47l.06,37.67-5.63,4.79-.07-42-44.57,37.86.07,42L182.8,206.46l.1,65.94,63.1-.1L245.83,163l13.33-11.34-.07-41.24A9.63,9.63,0,0,0,255.21,92Zm-50,154.79A3.92,3.92,0,0,1,209,250a3.85,3.85,0,0,1,.06.69,3.93,3.93,0,1,1-7.85,0,3.89,3.89,0,0,1,.08-.78A3.94,3.94,0,0,1,205.18,246.79Zm33.1,17.81-47.69.08L190.51,210l10.74-9.12.07,41a9.64,9.64,0,1,0,7.7,0L209,194.35l29.18-24.78Zm-.17-105.13-29.18,24.79-.05-31.88,29.18-24.8Zm20.83-56.59a3.92,3.92,0,0,1-7.43,0,4.2,4.2,0,0,1-.2-1.25,3.92,3.92,0,0,1,7.84,0A3.69,3.69,0,0,1,258.94,102.88Z" />
        </g>
      </g>
    </svg>
  </div>
</template>

<script>
  export default {};
</script>

<style module>
  .logo {
    padding: 4px;
    border-radius: 17px;
    width: 36px;
    height: 36px;
    color: #fff;

    @media print {
      color: #444;
    }
  }
</style>
