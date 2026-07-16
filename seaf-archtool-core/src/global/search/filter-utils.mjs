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

import { arrayOperators, relOperators, stringOperators, universalOperators } from './constants.mjs';
import { resolveRefTitles } from './search-utils.mjs';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

const LOG_TAG = 'filter-utils';
const logger = getLoggerWithTag(LOG_TAG);

export function filterValue({ entity, filters, entitySchema, manifest, relFieldsMap = {}, entityDataMap = {} }) {
    if (!filters || filters.length === 0) {
        return true;
    }

    // Проходим по всем фильтрам (AND логика)
    for (const filter of filters) {
        const { field, operator, value, not = false, ignoreCase = false } = filter;

        // Получаем значение из entity
        const entityValue = entity[field];

        // Поле-ссылка: фильтрация по названиям связанных объектов
        const relMeta = relFieldsMap[field];
        if (relMeta && manifest) {
            if (!relOperators.includes(operator)) {
                logger.debug(() => `Operator ${operator} is not valid for rel field ${field}`);
                return false;
            }
            const titlesText = resolveRefTitles(manifest, relMeta.relTarget, entityValue, entityDataMap);
            let match = false;
            if (operator === 'exists') {
                match = entityValue !== undefined && entityValue !== null
                    && (Array.isArray(entityValue) ? entityValue.length > 0 : String(entityValue).trim() !== '');
            } else {
                if (value == null || (typeof value === 'string' && value.trim() === '')) {
                    match = true;
                } else {
                    const searchStr = typeof value === 'string' ? value : String(value);
                    switch (operator) {
                        case 'contains':
                            match = contains(titlesText, searchStr, ignoreCase);
                            break;
                        case 'eq':
                            match = equals(titlesText, searchStr, ignoreCase);
                            break;
                        case 'startsWith':
                            match = startsWith(titlesText, searchStr, ignoreCase);
                            break;
                        case 'endsWith':
                            match = endsWith(titlesText, searchStr, ignoreCase);
                            break;
                        default:
                            match = false;
                    }
                }
            }
            if (not) match = !match;
            if (!match) return false;
            continue;
        }

        // Обычные поля
        const fieldType = entitySchema?.[field]?.type ?? (entitySchema?.[field]?.enum ? 'enum' : null);
        if (!isOperatorValidForType(operator, fieldType)) {
            logger.debug(`Operator ${operator} is not valid for field type ${fieldType}`);
            return false;
        }

        let match = false;
        switch (operator) {
            case 'eq':
                match = equals(entityValue, value, ignoreCase);
                break;

            case 'gt':
                match = entityValue > value;
                break;

            case 'gte':
                match = entityValue >= value;
                break;

            case 'lt':
                match = entityValue < value;
                break;

            case 'lte':
                match = entityValue <= value;
                break;

            case 'contains':
                match = contains(entityValue, value, ignoreCase);
                break;

            case 'startsWith':
                match = startsWith(entityValue, value, ignoreCase);
                break;

            case 'endsWith':
                match = endsWith(entityValue, value, ignoreCase);
                break;

            case 'in':
                match = isIn(entityValue, value, ignoreCase);
                break;

            case 'between':
                match = isBetween(entityValue, value);
                break;

            case 'exists':
                match = entityValue !== undefined && entityValue !== null;
                break;

            default:
                logger.debug(`Unknown operator: ${operator}`);
                return false;
        }

        if (not) match = !match;
        if (!match) return false;
    }

    return true;
}

// Вспомогательные функции для проверки типов операторов
function isOperatorValidForType(operator, fieldType) {
    switch (fieldType) {
        case 'string':
            return true; // все операторы могут применяться к строкам (числовые дадут false)

        case 'number':
        case 'integer':
            return !stringOperators.includes(operator) || operator === 'contains'; // contains может работать с числами как со строками

        case 'boolean':
            return universalOperators.includes(operator);

        case 'array':
            return [...universalOperators, ...arrayOperators].includes(operator);

        case 'object':
            return universalOperators.includes(operator);

        default:
            return true; // если тип неизвестен, разрешаем все операторы
    }
}

// Функции сравнения
function equals(a, b, ignoreCase = false) {
    if (a === null || a === undefined || b === null || b === undefined) {
        return a === b;
    }

    if (ignoreCase && typeof a === 'string' && typeof b === 'string') {
        return a.toLowerCase() === b.toLowerCase();
    }

    return a === b;
}

function contains(value, search, ignoreCase = false) {
    if (value === null || value === undefined) return false;

    // Для массивов
    if (Array.isArray(value)) {
        if (ignoreCase && typeof search === 'string') {
            return value.some(item =>
                typeof item === 'string' && item.toLowerCase().includes(search.toLowerCase())
            );
        }
        return value.includes(search);
    }

    // Для строк
    if (typeof value === 'string' && typeof search === 'string') {
        if (ignoreCase) {
            return value.toLowerCase().includes(search.toLowerCase());
        }
        return value.includes(search);
    }

    // Для чисел - конвертируем в строку
    if (typeof value === 'number' && typeof search === 'number') {
        return value.toString().includes(search.toString());
    }

    return false;
}

function startsWith(value, search, ignoreCase = false) {
    if (typeof value !== 'string' || typeof search !== 'string') return false;

    if (ignoreCase) {
        return value.toLowerCase().startsWith(search.toLowerCase());
    }
    return value.startsWith(search);
}

function endsWith(value, search, ignoreCase = false) {
    if (typeof value !== 'string' || typeof search !== 'string') return false;

    if (ignoreCase) {
        return value.toLowerCase().endsWith(search.toLowerCase());
    }
    return value.endsWith(search);
}

function isIn(value, allowedValues, ignoreCase = false) {
    if (!Array.isArray(allowedValues)) return false;

    if (ignoreCase && typeof value === 'string') {
        return allowedValues.some(v =>
            typeof v === 'string' && v.toLowerCase() === value.toLowerCase()
        );
    }

    return allowedValues.includes(value);
}

function isBetween(value, range) {
    if (!Array.isArray(range) || range.length !== 2) return false;

    const [min, max] = range;
    return value >= min && value <= max;
}
