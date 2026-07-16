/*
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
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber

  Contributors:
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
*/

import {getLogger} from '@global/logger/v2/logger.mjs';

let logger = getLogger();

export const recorder = {
	jsonataStore: {},
    perfLogger: logger,
    observer: null,
    reportJsonata(funcId, duration) {
        if (!this.jsonataStore[funcId]) this.jsonataStore[funcId] = {};
        this.jsonataStore[funcId].duration = (this.jsonataStore[funcId].duration || 0) + duration;
        this.jsonataStore[funcId].count = (this.jsonataStore[funcId].count || 0) + 1;
    }
};
