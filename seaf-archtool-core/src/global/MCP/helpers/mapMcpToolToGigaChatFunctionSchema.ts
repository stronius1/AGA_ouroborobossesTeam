import type { Tool } from '@modelcontextprotocol/sdk/types';
import { Function as GigaChatFunction } from 'gigachat/interfaces';

/**
 * JSON Schema для аргументов / ответа функции в формате GigaChat (поля `parameters`, `return_parameters`).
 * Подмножество JSON Schema: type, properties, items, required, description, enum, default, числовые и строковые ограничения.
 */
export type GigaChatJsonSchemaFragment = Record<string, unknown>;

/**
 * Описание одной функции для GigaChat API (tools / functions).
 * Имя и схемы должны соответствовать требованиям провайдера.
 */
export type GigaChatFunctionSchema = GigaChatFunction;

export interface MapMcpToolToGigaChatOptions {
  /** MCP не передаёт примеры; можно задать вручную по имени инструмента. */
  few_shot_examples?: GigaChatFunctionSchema['few_shot_examples'];
}

const EMPTY_OBJECT_SCHEMA: GigaChatJsonSchemaFragment = {
  type: 'object',
  properties: {}
};

/** Типы `type`, которые GigaChat принимает как одну строку (не массив union). */
const GIGACHAT_JSON_TYPE = new Set([
  'string',
  'number',
  'integer',
  'boolean',
  'array',
  'object'
]);

/**
 * API GigaChat не принимает JSON Schema с `type: string[]` (например `["string","null"]` из Zod).
 * Схлопываем в одну строку: первый известный тип, иначе `string`.
 */
function normalizeJsonSchemaTypeField(type: unknown): string | undefined {
  if (typeof type === 'string' && GIGACHAT_JSON_TYPE.has(type)) {
    return type;
  }
  if (Array.isArray(type)) {
    const nonNull = type.filter(
      (t): t is string => typeof t === 'string' && t !== 'null'
    );
    const known = nonNull.find((t) => GIGACHAT_JSON_TYPE.has(t));
    if (known) {
      return known;
    }
    return nonNull.length > 0 ? 'string' : 'string';
  }
  return undefined;
}

/**
 * Zod / json-schema часто дают `oneOf`/`anyOf` из веток `{ "const": "x" }`.
 * GigaChat ожидает `type` + `enum` для таких полей (см. truncateMode и т.п.).
 */
function tryFlattenOneOfAnyOfToEnum(obj: Record<string, unknown>): void {
  for (const key of ['oneOf', 'anyOf'] as const) {
    const arr = obj[key];
    if (!Array.isArray(arr) || arr.length === 0) {
      continue;
    }
    const values: unknown[] = [];
    let ok = true;
    for (const branch of arr) {
      if (
        branch &&
        typeof branch === 'object' &&
        !Array.isArray(branch) &&
        'const' in (branch as Record<string, unknown>)
      ) {
        values.push((branch as Record<string, unknown>).const);
      } else {
        ok = false;
        break;
      }
    }
    if (ok && values.length === arr.length) {
      delete obj[key];
      obj.enum = values;
      break;
    }
  }
}

function mergeConstIntoEnum(obj: Record<string, unknown>): void {
  if (!('const' in obj)) {
    return;
  }
  const c = obj.const;
  delete obj.const;
  if (!Array.isArray(obj.enum)) {
    obj.enum = [c];
  } else if (!(obj.enum as unknown[]).includes(c)) {
    (obj.enum as unknown[]).push(c);
  }
}

/**
 * Для поля с `enum` API GigaChat ожидает согласованный скалярный `type` (часто `string`).
 * Исправляет рассинхрон вроде `type: "integer"` при строковых литералах в enum.
 */
function alignTypeWithEnumValues(obj: Record<string, unknown>): void {
  if (!Array.isArray(obj.enum) || obj.enum.length === 0) {
    return;
  }
  const values = obj.enum as unknown[];
  const allString = values.every((v) => typeof v === 'string');
  const allNumber = values.every(
    (v) => typeof v === 'number' && !Number.isNaN(v as number)
  );
  const allBool = values.every((v) => typeof v === 'boolean');
  if (allString) {
    obj.type = 'string';
    return;
  }
  if (allNumber) {
    const allInt = values.every(
      (v) => typeof v === 'number' && Number.isInteger(v as number)
    );
    obj.type = allInt ? 'integer' : 'number';
    return;
  }
  if (allBool) {
    obj.type = 'boolean';
    return;
  }
  obj.type = 'string';
}

/**
 * Листья схемы: привести const / oneOf / enum к виду, который принимает GigaChat.
 */
function finalizePrimitiveSchemaForGigaChat(
  obj: Record<string, unknown>
): void {
  tryFlattenOneOfAnyOfToEnum(obj);
  mergeConstIntoEnum(obj);
  alignTypeWithEnumValues(obj);
}

/**
 * Рекурсивно приводит фрагмент JSON Schema к ограничениям GigaChat.
 */
export function normalizeJsonSchemaForGigaChat(node: unknown): unknown {
  if (node === null || typeof node !== 'object') {
    return node;
  }
  if (Array.isArray(node)) {
    return node.map((item) => normalizeJsonSchemaForGigaChat(item));
  }

  const obj: Record<string, unknown> = {
    ...(node as Record<string, unknown>)
  };

  if ('type' in obj) {
    const single = normalizeJsonSchemaTypeField(obj.type);
    if (single !== undefined) {
      obj.type = single;
    }
  }

  /**
   * GigaChat требует у каждого `type: "object"` явный ключ `properties` в схеме
   * (см. валидацию вроде `...environment.properties is missing`).
   * Zod/MCP часто дают только `additionalProperties` или пустой объект без `properties`.
   */
  const propertiesLookLikeObject =
    obj.properties !== undefined &&
    typeof obj.properties === 'object' &&
    obj.properties !== null &&
    !Array.isArray(obj.properties);

  if (
    obj.type === undefined &&
    (propertiesLookLikeObject ||
      obj.additionalProperties !== undefined ||
      obj.patternProperties !== undefined)
  ) {
    obj.type = 'object';
  }

  if (obj.type === 'object') {
    if (
      obj.properties === undefined ||
      obj.properties === null ||
      typeof obj.properties !== 'object' ||
      Array.isArray(obj.properties)
    ) {
      obj.properties = {};
    }
  }

  if (
    typeof obj.properties === 'object' &&
    obj.properties !== null &&
    !Array.isArray(obj.properties)
  ) {
    const props = obj.properties as Record<string, unknown>;
    const next: Record<string, unknown> = {};
    for (const [key, val] of Object.entries(props)) {
      next[key] = normalizeJsonSchemaForGigaChat(val);
    }
    obj.properties = next;
  }

  if (obj.items !== undefined) {
    if (Array.isArray(obj.items)) {
      obj.items =
        obj.items.length > 0
          ? normalizeJsonSchemaForGigaChat(obj.items[0])
          : { type: 'string' };
    } else {
      obj.items = normalizeJsonSchemaForGigaChat(obj.items);
    }
  }

  if (
    typeof obj.additionalProperties === 'object' &&
    obj.additionalProperties !== null &&
    !Array.isArray(obj.additionalProperties)
  ) {
    obj.additionalProperties = normalizeJsonSchemaForGigaChat(
      obj.additionalProperties
    );
  }

  finalizePrimitiveSchemaForGigaChat(obj);

  return obj;
}

function normalizeObjectSchema(
  schema: Tool['inputSchema'] | NonNullable<Tool['outputSchema']> | undefined,
  fallback: GigaChatJsonSchemaFragment
): GigaChatJsonSchemaFragment {
  if (!schema || typeof schema !== 'object') {
    return { ...fallback };
  }
  const o = schema as Record<string, unknown>;
  if (o.type !== 'object') {
    return { ...fallback };
  }
  const clone = JSON.parse(JSON.stringify(o)) as GigaChatJsonSchemaFragment;
  return normalizeJsonSchemaForGigaChat(clone) as GigaChatJsonSchemaFragment;
}

/**
 * Приводит инструмент MCP (`tools/list`) к схеме функции GigaChat:
 * `inputSchema` → `parameters`, `outputSchema` → `return_parameters` (если есть).
 */
export function mapMcpToolToGigaChatFunctionSchema(
  tool: Tool,
  options?: MapMcpToolToGigaChatOptions
): GigaChatFunctionSchema {
  const out: GigaChatFunctionSchema = {
    name: tool.name,
    description: tool.description ?? '',
    parameters: normalizeObjectSchema(tool.inputSchema, EMPTY_OBJECT_SCHEMA)
  };

  if (tool.outputSchema) {
    out.return_parameters = normalizeObjectSchema(
      tool.outputSchema,
      EMPTY_OBJECT_SCHEMA
    );
  }

  if (options?.few_shot_examples !== undefined) {
    out.few_shot_examples = options.few_shot_examples;
  }

  return out;
}

/**
 * Маппинг списка инструментов из ответа `mcpClient.listTools()`.
 */
export function mapMcpToolsToGigaChatFunctionSchemas(
  tools: Tool[],
  fewShotByToolName?: Record<
    string,
    NonNullable<GigaChatFunctionSchema['few_shot_examples']>
  >
): GigaChatFunctionSchema[] {
  return tools.map((tool) =>
    mapMcpToolToGigaChatFunctionSchema(tool, {
      few_shot_examples: fewShotByToolName?.[tool.name]
    })
  );
}
