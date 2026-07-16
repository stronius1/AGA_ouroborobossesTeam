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

export default function generateDatasetErrorDesc(id, error) {
    let output = `Ошибка при обсчёте датасета ${id}.\n${typeof error === 'string' ? error : error.message ?? ''}`;
    if (error.code) {
        output += `\nКод ошибки: ${error.code}.`;
    }
    if (error.value) {
        output += `\nЗаписанное значение: ${error.value}.`;
    }
    if (error.position) {
        output += `\nНа позиции ${error.position}.`;
    }
    if (error.token) {
        output += `\nОшибочный токен: ${error.token}.`;
    }
    return output;
}
