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
      Sergeev Viktor, Sber

  Contributors:
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
*/

import {describe, expect} from '@jest/globals';
import driver from '@global/jsonata/driver.mjs';
import schema from '../../__fixtures__/jsonata/validator/schema.json';
import data from '../../__fixtures__/jsonata/validator/data.json';

/**
 * Результаты валидации данных. Ожидается структура содержащая атрибуты в корне:
 * - instancePath
 * - schemaPath
 * - keyword
 * - message
 * и атрибуты $.attrInfo:,name,title,type,currentValue
 */
let validationResult;

beforeAll(async() => {
  // jsonata запрос для валидации данных по схеме. Схема и данные подгружаются из ресурсов
  const expression = `(
    $validator := $jsonschema($params.schema);
    $validator($params.data);
  )`;
  const evaluator = driver.expression(expression, null, {
    schema: schema,
    data: data
  });
  validationResult = await evaluator.evaluate({});
  if (validationResult === true) {
    throw new Error('Тест не может запуститься, т.к. evaluator.evaluate({}) вернул ответ, что ошибок нет, а они должны быть');
  }
});

describe.skip('Проверка атрибутов в ответе валидатора jsonata', () => {

  test('Все ответы содержат стандартные атрибуты',  () =>{
    const standartAttr = ['instancePath', 'schemaPath', 'keyword', 'message'];
    const errors = [];
    validationResult.forEach((el) => {
      standartAttr.forEach( attrName => {
        try {
          expect(el).toHaveProp(attrName);
        } catch (e) {
          errors.push(e.message);
        }
      });
    });

    if (errors.length > 0) {
      throw new Error(`Проверка провалилась для некоторых элементов:\n${errors.join('\n')}`);
    }
  });

  test('В этом сценарии, должно вернуться ровно 20 ошибок',  () =>{
    expect(validationResult).toHaveLength(20);
  });

  test.each([
    ['error_required_def', { type: 'string', title: 'Описание для атрибута, который обязательный, но его нет в single def' }],
    ['error_required', { type: 'string', title: 'Описание для атрибута, который обязательный, но его нет в prop' }]
  ])('Проверка элемента %s', (name, expectedInfo) => {
      const actual = validationResult.find((el) => el.attrInfo.name === name);
      if (!actual) {
        throw new Error(`Среди ошибок не найдена ошибка для атрибута ${name}, а она должна быть`);
      }
      expect(actual.attrInfo.title).toBe(expectedInfo.title);
      expect(actual.attrInfo.type).toBe(expectedInfo.type);
      expect(actual.attrInfo.currentValue).toBeUndefined();
    });

  test.each([
    ['error_max_length_def', { type: 'string', title: 'Описание для строки, больше лимита в single def', currentValue: 'Система_def' }],
    ['error_min_length_def', { type: 'string', title: 'Описание для строки, меньше лимита в single def', currentValue: 'С_def' }],
    ['error_type_def', { type: 'integer', title: 'Описание для атрибута с некорректным типом в single def', currentValue: 'Привет_def' }],
    ['error_pattern_def', { type: 'string', title: 'Описание для атрибута, нарушающего паттерн в single def', currentValue: 'ABCD-BBC_def' }],
    ['error_format_date_def', { type: 'string', title: 'Описание для атрибута с некорректной датой в single def', currentValue: 'test_def' }],
    ['error_enum_def', { type: 'string', title: 'Описание для атрибута с некорректным значением из enum в single def', currentValue: 'abc_def' }],
    ['master_system', { type: 'string', title: 'АС, являющаяся мастер системой для объекта данных', currentValue: 'sber.systems.paymentgate' }],
    ['systems_array[0]', { type: 'array', title: 'Системы, в которых реализована (планируется к реализации)', currentValue: 'ecogroup.berezka.systems.berezka3' }],
    ['systems_array[2]', { type: 'array', title: 'Системы, в которых реализована (планируется к реализации)', currentValue: 'ecogroup.berezka.systems.berezka2' }],
    ['systems_array_deep[0][0]', { type: 'array', title: 'Системы, в которых реализована (планируется к реализации)', currentValue: 'ecogroup.berezka.systems.berezka00' }],
    ['systems_array_deep[1][1]', { type: 'array', title: 'Системы, в которых реализована (планируется к реализации)', currentValue: 'ecogroup.berezka.systems.berezka11' }],
    ['systems_array_deep[2][0]', { type: 'array', title: 'Системы, в которых реализована (планируется к реализации)', currentValue: 'ecogroup.berezka.systems.berezka20' }],
    ['error_max_length', { type: 'string', title: 'Описание для строки, больше лимита в prop', currentValue: 'Система' }],
    ['error_min_length', { type: 'string', title: 'Описание для строки, меньше лимита в prop', currentValue: 'С' }],
    ['error_type', { type: 'integer', title: 'Описание для атрибута с некорректным типом в prop', currentValue: 'Привет' }],
    ['error_pattern', { type: 'string', title: 'Описание для атрибута, нарушающего паттерн в prop', currentValue: 'ABCD-BBC' }],
    ['error_format_date', { type: 'string', title: 'Описание для атрибута с некорректной датой в prop', currentValue: 'test' }],
    ['error_enum', { type: 'string', title: 'Описание для атрибута с некорректным значением из enum в prop', currentValue: 'abc' }]
  ])('Проверка элемента %s', (name, expectedInfo) => {
    const actual = validationResult.find((el) => el.attrInfo.name === name);
    if (!actual) {
      throw new Error(`Среди ошибок не найдена ошибка для атрибута ${name}, а она должна быть`);
    }
    expect(actual.attrInfo.title).toBe(expectedInfo.title);
    expect(actual.attrInfo.type).toBe(expectedInfo.type);
    expect(actual.attrInfo.currentValue).toBe(expectedInfo.currentValue);
  });
});

/**
 * Кастомный матчер для проверки, что у объекта есть атрибут {property}
 * и этот атрибут не пустой (не null и не undefined)
 */
expect.extend({
  toHaveProp(validatorResultElement, property) {
    const hasProp = Object.prototype.hasOwnProperty.call(validatorResultElement, property);
    const value = validatorResultElement?.[property];

    let attrName = validatorResultElement.attrInfo.name;
    const pass = hasProp && value !== null && value !== undefined;

    return {
      pass,
      message: () =>
        pass
          ? `expected object (${attrName}) not to have defined and non-null property '${property}'`
          : `expected object (${attrName}) to have property '${property}' with non-null and defined value`
    };
  }
});
