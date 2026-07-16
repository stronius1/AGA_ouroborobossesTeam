/*
  Copyright (C) 2025 Sber

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
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber

  Contributors:
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
*/

import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

const logger = getLoggerWithTag('loggerExtension');

/**
 * Метод выводит в лог последовательность отрисованных компонентов, по сути дерево вложенности относительно переданного компонента
 * @param positionName - место откуда вызывается метод, какая-то пометка, чтобы отличать записи в логе, контекст
 * @param comp - сам компонент, который сейчас отрисовывается
 */
export const logComponentTree = (positionName: string, comp: any) => {
  logger.trace(() => {
    const path = [];
    let current = comp;
    while (current) {
      path.unshift(current.$options.name + ':' + current.$.uid || 'anonymous');
      current = current.$parent;
    }
    return [`${positionName}: ${path.join(' -> ')}`];
  });
};
