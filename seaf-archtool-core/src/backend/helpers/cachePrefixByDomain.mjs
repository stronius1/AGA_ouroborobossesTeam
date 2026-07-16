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
 * Получить префикс для кеша, составляется их hash манифеста и домена при наличии
 * @param storage - данные манифеста
 * @param hash - опциональный параметр, если надо указать другой хеш, например для старого манифеста
 * @returns {string}
 */
export function getCachePrefixWithDomain(storage, hash = storage.hash) {
    let cachePrefixReal = hash;
    if (storage.permission) {
        cachePrefixReal = `${hash}.${storage.permission}`;
    }
    return cachePrefixReal;
}

/**
 * Получить префикс для кеширования чексум датасетов
 * @param storage
 * @param hash - опциональный параметр, если надо указать другой хеш, например для старого манифеста
 * @returns {string}
 */
export function getDsChecksumPrefixWithDomain(storage, hash = storage.hash) {
    return getCachePrefixWithDomain(storage, hash) + '.dsChecksum';
}
