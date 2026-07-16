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
  import errConstants from '@front/constants/errConstants.json';
  import { h } from 'vue';

  export default {
    props: { error: { type: String, default: '' } },
    render() {
      return h('section', { class: 'errorSection' }, [
        h('h1', errConstants.LOAD_ERROR),
        h('p', { innerHTML: this.error })
      ]);
    }
  };
</script>

<style scoped>
  .errorSection {
    top: 5%;
    color: #FF0000;
    text-align: center;
    position: relative;
  }

  .errorSection p {
    white-space: pre;
  }
</style>
