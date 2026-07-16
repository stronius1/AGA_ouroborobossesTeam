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

/**
 * Преобразование функции сообщения лога в массив строк для записи
 * Все сообщения в логгер передаются как функция, которая вычисляется только если уровень лога позволяет записать лог
 * Сначала функция выполняется, если все хорошо то далее содержимое преобразуется к строкам
 * @param message - функция возвращающая то, что нужно записать в лог
 */
export function logMessageToStringArray(message) {
    if (!message) {
        return ['[empty message in log row]'];
    }
    let result= [];
    // пробуем выполнить переданную функцию
    try {
        result = message();
    } catch (error) {
        // eslint-disable-next-line no-console
        console.error('[Logger] Message evaluation failed:', error);
        return ['[Message computation error]'];
    }
    if (Array.isArray(result)) {
        return result.map(el => {
            if (typeof el === 'string') {
                return el;
            } else if (el) {
                try {
                    return `${el.title} ${JSON.stringify(el.obj)}`;
                } catch (e) {
                    return `${el.title} [JSON.stringify(el.obj) error ${e.message}]`;
                }
            }
        });
    } else {
        // Если строка — завернём в массив
        return [result];
    }

}
