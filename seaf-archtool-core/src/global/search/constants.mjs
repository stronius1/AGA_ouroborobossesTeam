/*
  Copyright (C) 2026 Sber

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  restrictions under the License.

  Maintainers:
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber

  Contributors:
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2026
      Marat Niyazmatov, Sber - 2026
*/

const RELS_REF_PREFIX = '#/$rels/';
const DEFS_REF_PREFIX = '#/$defs/';

// Операторы для всех типов
const universalOperators = ['eq', 'exists'];
// Операторы только для строк
const stringOperators = ['contains', 'startsWith', 'endsWith'];
// Операторы для массивов
const arrayOperators = ['in', 'contains']; // contains для массивов тоже работает
// Операторы для отношений
const relOperators = ['contains', 'eq', 'startsWith', 'endsWith', 'exists'];

const SEARCH_ALL_KEY = '__all__';
const SEARCH_RESULT_LIMIT = 10_000;

const PRESENTATION_PRIORITY = ['card', 'blank', 'schema'];

const REL_SUGGESTIONS_LIMIT = 50;


export {
    RELS_REF_PREFIX,
    DEFS_REF_PREFIX,
    SEARCH_ALL_KEY,
    SEARCH_RESULT_LIMIT,
    PRESENTATION_PRIORITY,
    universalOperators,
    stringOperators,
    arrayOperators,
    relOperators,
    REL_SUGGESTIONS_LIMIT
};
