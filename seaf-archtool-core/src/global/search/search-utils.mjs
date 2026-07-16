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

import { DEFS_REF_PREFIX, PRESENTATION_PRIORITY, RELS_REF_PREFIX } from './constants.mjs';
import { getSearchableEntityIds } from './search-config.mjs';
/**
 * Рекурсивно собирает поля со ссылками на $rels из схемы сущности.
 * @param {object} fullSchema - Полная схема (req.storage.schema или manifest)
 * @param {string} choice - Идентификатор сущности (entityId)
 * @param {object} manifest - Манифест для fallback (manifest.entities[choice]?.schema)
 * @returns {Array<{key: string, relTarget: string, isArray: boolean, title?: string}>}
 */
export function collectRelFields(fullSchema, choice, manifest) {
    const entitySchema = fullSchema?.properties?.[choice] ?? manifest?.entities?.[choice]?.schema;
    const defs = { ...(entitySchema?.$defs ?? {}), ...(fullSchema?.$defs ?? {}) };
    if (!entitySchema || typeof entitySchema !== 'object') {
        return [];
    }

    const result = new Map();
    const processedDefs = new Set();

    function visit(node, fieldName, isArray, title) {
        if (!node || typeof node !== 'object') return;

        if (node.$ref) {
            const ref = String(node.$ref);
            if (ref.startsWith(RELS_REF_PREFIX)) {
                const relTarget = ref.slice(RELS_REF_PREFIX.length);
                if (fieldName && !result.has(fieldName)) {
                    result.set(fieldName, {
                        key: fieldName,
                        relTarget,
                        isArray: !!isArray,
                        title: node.title ?? title
                    });
                }
                return;
            }
            if (ref.startsWith(DEFS_REF_PREFIX)) {
                const defKey = ref.slice(DEFS_REF_PREFIX.length);
                if (processedDefs.has(defKey)) return;
                processedDefs.add(defKey);
                const defNode = defs[defKey];
                if (defNode) {
                    visit(defNode, fieldName, isArray, title);
                }
                processedDefs.delete(defKey);
                return;
            }
        }

        if (node.properties) {
            for (const [k, v] of Object.entries(node.properties)) {
                visit(v, k, isArray, v?.title);
            }
        }
        if (node.items) {
            visit(node.items, fieldName, true, node.title ?? title);
        }
        if (Array.isArray(node.allOf)) {
            for (const s of node.allOf) visit(s, fieldName, isArray, title);
        }
        if (Array.isArray(node.oneOf)) {
            for (const s of node.oneOf) visit(s, fieldName, isArray, title);
        }
        if (Array.isArray(node.anyOf)) {
            for (const s of node.anyOf) visit(s, fieldName, isArray, title);
        }
        if (node.patternProperties && typeof node.patternProperties === 'object') {
            for (const v of Object.values(node.patternProperties)) {
                visit(v, fieldName, isArray, title);
            }
        }
    }

    visit(entitySchema, null, false, undefined);
    return Array.from(result.values());
}

/**
 * Парсит relTarget в entityId и subjectId.
 * @param {string} relTarget - формат: "entityId.subjectId" (напр. "kadzo.v2023.groups.groups")
 */
export function parseRelTarget(relTarget) {
    if (!relTarget || typeof relTarget !== 'string') return null;
    const lastDot = relTarget.lastIndexOf('.');
    if (lastDot < 0) return { entityId: relTarget, subjectId: null };
    return {
        entityId: relTarget.slice(0, lastDot),
        subjectId: relTarget.slice(lastDot + 1)
    };
}

export function collectTopLevelProperties(obj) {
    const result = {};
    const stack = [obj];
    const processed = new Set();

    while (stack.length > 0) {
        const current = stack.pop();

        if (!current || typeof current !== 'object' || processed.has(current)) {
            continue;
        }

        processed.add(current);

        // Если у текущего объекта есть properties, добавляем их
        if (current.properties && typeof current.properties === 'object') {
            Object.assign(result, current.properties);
        }

        // Добавляем все поля в стек, КРОМЕ properties
        for (const key in current) {
            // Пропускаем поле properties
            if (key === 'properties') continue;

            const value = current[key];
            if (value && typeof value === 'object') {
                if (Array.isArray(value)) {
                    // Для массивов добавляем каждый элемент
                    for (let i = 0; i < value.length; i++) {
                        if (value[i] && typeof value[i] === 'object') {
                            stack.push(value[i]);
                        }
                    }
                } else {
                    stack.push(value);
                }
            }
        }
    }

    return result;
}

export function getTitleDescriptionFields(allProperties) {
    const stringFields = Object.entries(allProperties)
        .filter(([, v]) => v?.type === 'string' || v?.enum)
        .map(([k]) => k);
    const titleKey = stringFields.find(k => /^title$|^name$|^label$/i.test(k)) || stringFields[0];
    const descKey = stringFields.find(k => /^description$|^desc$/i.test(k));
    return { titleKey, descKey, stringFields };
}

export function getObjectTitle(obj, { titleKey }) {
    if (titleKey && obj[titleKey] != null) return String(obj[titleKey]);
    return obj.title ?? obj.name ?? obj.label ?? obj._sfa_key ?? '—';
}

/**
 * Преобразует ID ссылок в строку названий (title + aliases) для поиска.
 * @param {object} manifest
 * @param {string} relTarget - entityId.subjectId
 * @param {string|string[]} ids - один ID или массив ID
 * @param {Record<string, Record<string, object>>} [entityDataMap]
 * @returns {string}
 */
export function resolveRefTitles(manifest, relTarget, ids, entityDataMap = {}) {
    const parsed = parseRelTarget(relTarget);
    if (!parsed) return '';
    const { entityId } = parsed;
    const entityData = entityDataMap[entityId] ?? manifest?.[entityId];
    if (!entityData || typeof entityData !== 'object') return '';

    const idList = Array.isArray(ids) ? ids : (ids != null && ids !== '' ? [ids] : []);
    const entityDef = manifest?.entities?.[entityId];
    const allProperties = entityDef?.schema ? collectTopLevelProperties(entityDef.schema) : null;
    const { titleKey } = getTitleDescriptionFields(allProperties || {});

    const parts = [];
    for (const id of idList) {
        if (id == null || typeof id !== 'string') continue;
        const obj = entityData[id];
        if (!obj) continue;
        const objWithKey = { ...obj, _sfa_key: id };
        const title = getObjectTitle(objWithKey, { titleKey });
        parts.push(title);
        if (Array.isArray(obj.aliases)) {
            parts.push(...obj.aliases.map(a => String(a)));
        }
    }
    return parts.join('; ');
}

export function getSearchableEntities(manifest) {
    return getSearchableEntityIds(manifest);
}

function getCompanyFromKey(key, companies = {}) {
    if (!key || typeof key !== 'string') return '—';
    const parts = key.split('.');
    const companyId = parts[0];
    const company = companies[companyId];
    return company?.title || companyId || '—';
}

function getObjectDescription(obj, { descKey }) {
    if (descKey && obj[descKey] != null) return String(obj[descKey]);
    return obj.description ?? obj.desc ?? '';
}

function matchWordsInText(text, words, ignoreCase = true) {
    if (!text || typeof text !== 'string') return false;
    const s = ignoreCase ? text.toLowerCase() : text;
    return words.every(w => s.includes(ignoreCase ? w.toLowerCase() : w));
}


function getLinkToPresForEntity(entityDef, entityId, key) {
    const presentations = entityDef?.presentations;
    if (!presentations || typeof presentations !== 'object') return null;
    for (const pid of PRESENTATION_PRIORITY) {
        if (pid in presentations && presentations[pid] != null) {
            // Проверяем параметры презы. Eсли он один, то предполагаем, что это идентификатор экземпляра сущности
            const parameterList = Object.keys(presentations[pid]?.params?.properties ?? {});
            const parameterIsSingle = parameterList.length === 1;
            if (parameterIsSingle) {
                return `/entities/${entityId}/${pid}?${parameterList[0]}=${encodeURIComponent(key)}`;
            }
        }
    }
}

export function buildSearchResultItem(key, value, entityId, entityTitle, companies, allProperties, entityDef) {
    const card = getLinkToPresForEntity(entityDef, entityId, key);
    const company = getCompanyFromKey(key, companies);
    const obj = { ...value, _sfa_key: key };
    const { titleKey, descKey } = allProperties
        ? getTitleDescriptionFields(allProperties)
        : { titleKey: 'title', descKey: 'description' };
    const title = getObjectTitle(obj, { titleKey });
    const description = getObjectDescription(obj, { descKey }, []);
    return {
        _sfa_key: key,
        _sfa_entity: entityId,
        company,
        entityTitle,
        title,
        description,
        card: card || undefined,
        ...value
    };
}

export function checkSearchQueryMatch(queryWords, key, value, titleKey, descKey) {
    const obj = { ...value, _sfa_key: key };
    const title = getObjectTitle(obj, { titleKey });
    const description = getObjectDescription(obj, { descKey }, []);
    const searchText = `${title} ${description}`.trim();
    const match = queryWords.length === 0
        ? true
        : queryWords.some(w => matchWordsInText(searchText, [w]));
    return match;
}
