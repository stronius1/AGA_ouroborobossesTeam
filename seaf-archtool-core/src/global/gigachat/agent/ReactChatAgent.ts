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
      Alexander Romashin, Sber

  Contributors:
      Alexander Romashin, Sber - 2025
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2025
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2026
*/

import { AiAgent } from '@global/gigachat/agent/AiAgent';
import { AgentType } from '@global/gigachat/agent/type/AgentType';
import { ReactAgentConfig } from '@global/gigachat/agent/type/ReactAgentConfig';
import { z } from 'zod';
import { ContentChunk } from '@global/gigachat/agent/type/ContentChunk';
import { getLoggerWithTag } from '@global/logger/v2/logger.mjs';
import { PullDataToolFn } from './type/PullDataToolFn';
import { LangchainSessionMessage } from '@global/gigachat/session/type/SessionMessage';
import { HumanMessage, AIMessage } from '@langchain/core/messages';
import {ReactSession, SessionSerializable} from '../session/type/SessionSerializable';
import {GigaChatClientConfig} from 'gigachat';

const LOGGER_NAME = 'ReactChatAgent';
const logger = getLoggerWithTag(LOGGER_NAME);

export class ReactChatAgent implements AiAgent {
  gigaChatClientConfig: GigaChatClientConfig;
  pullDataTool: PullDataToolFn;

  constructor(
      gigaChatClientConfig: GigaChatClientConfig
  ) {
    this.gigaChatClientConfig = gigaChatClientConfig;
  }

  type: AgentType = 'react';
  description = 'ReAct-агент';

  async fillNewChat(
      systemPrompt: string,
      sessionSerializable: SessionSerializable
  ): Promise<void> {
    this.pullDataTool = sessionSerializable.config.pullDataTool;
  }

  async *handleMessage(
    message: string,
    session: SessionSerializable
  ): AsyncIterable<ContentChunk> {
    const reactSession = session as ReactSession;
    
    // Сохраняем количество сообщений до добавления нового human сообщения
    const messageCountBeforeUserInput = reactSession.messages.length;

    reactSession.messages.push(new HumanMessage(message));

    const config = reactSession.config as ReactAgentConfig | undefined;
    const tools = config?.tools || [];

    // Попытка распознать вызов инструмента в сообщении пользователя
    const toolCall = parseToolCall(message);
    if (toolCall) {
      const toolDef = tools.find((t) => t.name === toolCall.name);
      if (!toolDef) {
        const content = `[react-tool:error] инструмент '${toolCall.name}' не найден`;
        reactSession.messages.push(new AIMessage(content));
        yield { content };
        return;
      }
      if (!this?.pullDataTool) {
        const content = '[react-tool:error] pullDataTool недоступен';
        reactSession.messages.push(new AIMessage(content));
        yield { content };
        return;
      }
      try {
        const parsedParams = validateParamsWithZod(
          toolDef.schema,
          toolCall.params || {}
        );
        const query = substitutePlaceholders(toolDef.query, parsedParams);
        const queryResponse = await this.pullDataTool(
          query,
          config?.jsonataParams,
          toolDef?.origin || config?.jsonataOrigin
        );

        // Проверяем, возвращает ли pullDataTool объект с result и logs
        let result: any;
        if (
          queryResponse &&
          typeof queryResponse === 'object' &&
          'result' in queryResponse
        ) {
          result = queryResponse.result;
          // Передаем логи через ContentChunk (если есть)
          if (queryResponse.logs && Array.isArray(queryResponse.logs)) {
            yield { logs: queryResponse.logs };
          }
        } else {
          // Обратная совместимость: если возвращается просто результат
          result = queryResponse;
        }

        const content = `[react-tool:${toolDef.name}] ${safeStringify(result)}`;
        reactSession.messages.push(new AIMessage(content));
        yield { content };
        return;
      } catch (e) {
        const content = `[react-tool:error] ${toolDef.name}: ${
          e?.message || e
        }`;
        reactSession.messages.push(new AIMessage(content));
        yield { content };
        return;
      }
    }

    // Если явного вызова инструмента нет — пробуем через LangChain-агента с включенными tools
    // eslint-disable-next-line no-useless-catch
    try {
      const { GigaChat: LCGigaChat } = await import('langchain-gigachat');
      const { DynamicStructuredTool } = await import('@langchain/core/tools');
      const { createReactAgent } = await import(
        '@langchain/langgraph/prebuilt'
      );
      const { MessagesAnnotation } = await import('@langchain/langgraph');

      const options = Object.assign({}, this.gigaChatClientConfig, {
        model:
          config?.model ||
          process.env.VUE_APP_GIGACHAT_DEFAULT_MODEL ||
          'GigaChat',
        temperature:
          typeof config?.temperature === 'number' ? config.temperature : 0,
        top_p: typeof config?.topP === 'number' ? config?.topP : undefined,
        maxRetries: 1
      });

      const lcModel = new LCGigaChat(options);

      // Добавляем обработчик для получения токенов
      let totalTokens = 0;
      let promptTokens = 0;
      let completionTokens = 0;

      let invokeCount = 0;

      // Перехватываем вызовы модели для получения токенов
      const originalInvoke = lcModel.invoke.bind(lcModel);
      lcModel.invoke = async function(
        input: Array<LangchainSessionMessage>,
        options?: any
      ) {

        logger.debug(() => `Session ${reactSession.id}. LanhChain the invoke #${++invokeCount} started...`);

        const result = await originalInvoke(input, options);

        logger.debug(() => `Session ${reactSession.id}. LanhChain the invoke #${invokeCount} was successful.`);

        // Пытаемся получить токены из результата
        if (result && typeof result === 'object') {

          // Проверяем разные возможные места для токенов
          if (result.usage_metadata) {
            totalTokens = result.usage_metadata.total_tokens || 0;
            promptTokens = result.usage_metadata.prompt_tokens || 0;
            completionTokens = result.usage_metadata.completion_tokens || 0;
            logger.debug(
              () =>
                `Session ${reactSession.id}. LangChain tokens (usage_metadata): total=${totalTokens}, prompt=${promptTokens}, completion=${completionTokens}.`
            );
          } else if (result.usage) {
            totalTokens = result.usage.total_tokens || 0;
            promptTokens = result.usage.prompt_tokens || 0;
            completionTokens = result.usage.completion_tokens || 0;
            logger.debug(
              () =>
                `Session ${reactSession.id}. LangChain tokens (usage): total=${totalTokens}, prompt=${promptTokens}, completion=${completionTokens}.`
            );
          } else if (
            result.response_metadata &&
            result.response_metadata.usage
          ) {
            totalTokens = result.response_metadata.usage.total_tokens || 0;
            promptTokens = result.response_metadata.usage.prompt_tokens || 0;
            completionTokens =
              result.response_metadata.usage.completion_tokens || 0;
            logger.debug(
              () =>
                `Session ${reactSession.id}. LangChain tokens (response_metadata.usage): total=${totalTokens}, prompt=${promptTokens}, completion=${completionTokens}.`
            );
          } else if (
            result.response_metadata &&
            result.response_metadata.usage_metadata
          ) {
            totalTokens =
              result.response_metadata.usage_metadata.total_tokens || 0;
            promptTokens =
              result.response_metadata.usage_metadata.prompt_tokens || 0;
            completionTokens =
              result.response_metadata.usage_metadata.completion_tokens || 0;
            logger.debug(
              () =>
                `Session ${reactSession.id}. LangChain tokens (response_metadata.usage_metadata): total=${totalTokens}, prompt=${promptTokens}, completion=${completionTokens}.`
            );
          } else {
            // Если не нашли токены, логируем структуру для отладки
            logger.debug(
              () => `Session ${reactSession.id}. LangChain response does not contain data about tokens.`);
          }

          // Fallback: если нашли total_tokens, но не нашли prompt/completion,
          // то пытаемся оценить разделение на основе длины входных и выходных данных
          if (totalTokens > 0 && promptTokens === 0 && completionTokens === 0) {
            // Пытаемся оценить токены запроса на основе входных сообщений
            const inputText = input
              .map(({ content }) => content || '')
              .join(' ');
            const outputText = result?.content || '';

            // Простая оценка: примерно 1 токен = 4 символа для русского текста
            const estimatedPromptTokens = Math.ceil(inputText.length / 4);
            const estimatedCompletionTokens = Math.ceil(outputText.length / 4);

            // Если оценка близка к общему количеству токенов, используем её
            if (
              estimatedPromptTokens + estimatedCompletionTokens <=
              totalTokens * 1.2
            ) {
              promptTokens = Math.min(estimatedPromptTokens, totalTokens);
              completionTokens = totalTokens - promptTokens;
              logger.debug(
                () =>
                  `Session ${reactSession.id}. LangChain estimated tokens: prompt=${promptTokens}, completion=${completionTokens} (from text length).`
              );
            } else {
              // Иначе считаем что все токены - это completion (ответ)
              completionTokens = totalTokens;
              logger.debug(
                () =>
                  `Session ${reactSession.id}. LangChain fallback: treating all ${totalTokens} tokens as completion.`
              );
            }
          }
        }

        return result;
      };

      const lcTools = (tools || []).map(
        (t) =>
          new DynamicStructuredTool({
            name: t.name,
            description: t.description,
            schema: buildZodFromSchema(t.schema),
            func: async(params) => {
              logger.debug(() => `Session ${reactSession.id}. LanhChain tool has been called.`);

              if (!this?.pullDataTool) {
                throw new Error('pullDataTool недоступен');
              }

              const query = substitutePlaceholders(t.query, params || {});

              const queryResponse = await this.pullDataTool(
                query,
                config?.jsonataParams,
                t?.origin || config?.jsonataOrigin
              );

              logger.debug(() => `Session ${reactSession.id}. LanhChain tool successfully completed the pullDataTool call.`);

              // Проверяем, возвращает ли pullDataTool объект с result и logs
              let result: any;
              if (
                queryResponse &&
                typeof queryResponse === 'object' &&
                'result' in queryResponse
              ) {
                result = queryResponse.result;
                // Выводим логи в консоль браузера (если есть)
                if (queryResponse.logs && Array.isArray(queryResponse.logs)) {
                  queryResponse.logs.forEach((logEntry: any) => {
                    logger.debug(
                      () =>
                        `[gigachat-log]${
                          logEntry.tag ? `[${logEntry.tag}]` : ''
                        }: `,
                      logEntry.content
                    );
                  });
                }
              } else {
                // Обратная совместимость: если возвращается просто результат
                result = queryResponse;
              }

              return safeStringify(result);
            }
          })
      );

      // Диагностика: выведем информацию о schema для каждого инструмента
      try {
        const { default: zodToJsonSchema } = await import('zod-to-json-schema');
        const toolSchemasDebug = (tools || []).map((t) => {
          const z = buildZodFromSchema(t.schema);
          const keys: string[] | undefined = z._def?.shape
            ? Object.keys(z._def.shape())
            : undefined;
          let jsonSchema: any;
          try {
            jsonSchema = zodToJsonSchema(z, { target: 'jsonSchema7' });
          } catch {
            jsonSchema = null;
          }
          return { name: t.name, zodType: z?._def?.typeName, keys, jsonSchema };
        });
        logger.debug(
          () => `Session ${reactSession.id}. Tools schemas:\n${JSON.stringify(toolSchemasDebug)}`
        );
      } catch (e) {
        logger.error(
          () =>
            `Session ${reactSession.id}. Couldn't get schema information for each tool`,
          e
        );
      }

      const agent = await createReactAgent({
        llm: lcModel,
        tools: lcTools,
        stateSchema: MessagesAnnotation
      });

      const lcMessages = reactSession.messages;

      // Логируем запрос к LangGraph
      logger.debug(() => `Session ${reactSession.id}. Request to LangGraph.`);
      logger.debug(() => `Session ${reactSession.id}. Messages count: ${lcMessages.length}`);
      logger.debug(() => `Session ${reactSession.id}. Tools count: ${tools.length}`);

      const result = await agent.invoke({ messages: lcMessages });

      // Получаем полную историю сообщений из результата агента
      const fullHistory = result?.messages || [];

      // Находим, какие сообщения являются новыми (появились после вызова агента)
      const expectedMessageCount = messageCountBeforeUserInput + 1;
      const newMessages = fullHistory.slice(expectedMessageCount);

      logger.debug(() => `Session ${reactSession.id}. The response was received successfull. New messages count: ${newMessages.length}. LangChain invoke count: ${invokeCount}.`);

      // Обновляем историю в сессии - сохраняем всю полную историю из LangGraph
      reactSession.messages = fullHistory;

      // Извлекаем только финальный ответ AI для отображения пользователю
      const finalAIMessage = newMessages.at(-1);

      // Отображаем финальный ответ пользователю
      if (finalAIMessage && finalAIMessage.content) {
        const content = finalAIMessage.content;

        // Передаем токены если они есть
        const tokens =
          totalTokens > 0
            ? {
                total: totalTokens,
                prompt: promptTokens,
                completion: completionTokens
              }
            : undefined;

        yield { content, tokens };
      } else if (newMessages.length > 0) {
        // Если нет финального AI сообщения, но есть новые сообщения
        logger.warn(
          () =>
            `Session ${reactSession.id}. No final AI message found, but ${newMessages.length} new messages were added.`
        );
      }
      return;
    } catch (e) {
      throw e;
    }
  }

  // глушу предупреждение т.к. метод пока остается, но ничего не делает
  // eslint-disable-next-line no-unused-vars
  async endChat(session: SessionSerializable): Promise<void> {
  }
}

type ToolCall = { name: string; params?: Record<string, any> } | null;

const parseToolCall = (input: string): ToolCall => {
  const trimmed = (input || '').trim();
  // Вариант 1: JSON-формат {"tool":"name", "params":{...}}
  try {
    const asJson = JSON.parse(trimmed);
    if (
      asJson &&
      typeof asJson === 'object' &&
      typeof asJson.tool === 'string'
    ) {
      return { name: asJson.tool, params: asJson.params || {} };
    }
  } catch (_) {
    // ignore
  }
  // Вариант 2: @tool <name> {json}
  const atToolMatch = trimmed.match(/^@tool\s+(\w+)(?:\s+(\{[\s\S]*\}))?$/i);
  if (atToolMatch) {
    const name = atToolMatch[1];
    const paramsRaw = atToolMatch[2];
    if (paramsRaw) {
      try {
        const params = JSON.parse(paramsRaw);
        return { name, params };
      } catch (_) {
        return { name };
      }
    }
    return { name };
  }
  // Вариант 3: tool:<name> key=value key2=value2
  const toolPrefix = trimmed.match(/^tool:(\w+)\s*(.*)$/i);
  if (toolPrefix) {
    const name = toolPrefix[1];
    const rest = toolPrefix[2] || '';
    const params: Record<string, any> = {};
    for (const token of rest.split(/\s+/).filter(Boolean)) {
      const eq = token.indexOf('=');
      if (eq > 0) {
        const k = token.slice(0, eq);
        const v = token.slice(eq + 1);
        params[k] = v;
      }
    }
    return { name, params };
  }
  return null;
};

const substitutePlaceholders = (
  query: string,
  params: Record<string, any>
): string => {
  if (!query) return query;
  let out = query;
  for (const [key, value] of Object.entries(params || {})) {
    const re = new RegExp(`\\$\\{${escapeRegExp(key)}\\}`, 'g');
    out = out.replace(re, String(value));
  }
  return out;
};

const escapeRegExp = (s: string): string =>
  s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

const safeStringify = (val: any): string => {
  try {
    return JSON.stringify(val);
  } catch {
    return String(val);
  }
};

const validateParamsWithZod = (
  schema: unknown,
  params: Record<string, any>
): Record<string, any> => {
  // schema может быть объектом вида {key: string | ZodType}
  if (!schema || typeof schema !== 'object') return params || {};
  const entries = Object.entries(schema as Record<string, unknown>).map(
    ([key, value]) => [
      key as string,
      typeof value === 'string'
        ? z.string().describe(value)
        : (value as z.ZodTypeAny)
    ]
  );
  const shape: Record<string, z.ZodTypeAny> = {} as Record<
    string,
    z.ZodTypeAny
  >;
  for (const [k, v] of entries as Array<[string, z.ZodTypeAny]>)
    shape[k] = v || z.any();
  const zodSchema = z.object(shape);
  const parse = zodSchema.safeParse(params || {});
  if (!parse.success) {
    throw new Error(
      'Неверные параметры инструмента: ' +
        parse.error.issues.map((i) => i.message).join('; ')
    );
  }
  return parse.data;
};

// Преобразование JSON Schema → Zod (подмножество: object/properties/required, string/number/integer/boolean, array(items), enum, вложенные объекты)
const jsonSchemaToZod = (schema: any): z.ZodTypeAny => {
  if (!schema || typeof schema !== 'object') return z.any();
  // enum
  if (Array.isArray(schema.enum) && schema.enum.length) {
    const values = schema.enum.map(String) as [string, ...string[]];
    return z.enum(values);
  }
  const type = schema.type;
  switch (type) {
    case 'string':
      return z.string();
    case 'integer':
      return z.number().int();
    case 'number':
      return z.number();
    case 'boolean':
      return z.boolean();
    case 'array': {
      const itemSchema = jsonSchemaToZod(schema.items || {});
      return z.array(itemSchema);
    }
    case 'object': {
      const properties = schema.properties || {};
      const required: string[] = Array.isArray(schema.required)
        ? schema.required
        : [];
      const shape: Record<string, z.ZodTypeAny> = {};
      for (const [propName, propSchema] of Object.entries(properties)) {
        let zodProp = jsonSchemaToZod(propSchema);
        // title/description → describe
        if (
          propSchema &&
          typeof propSchema === 'object' &&
          (propSchema as any).description
        ) {
          zodProp = (zodProp as any).describe((propSchema as any).description);
        } else if (
          propSchema &&
          typeof propSchema === 'object' &&
          (propSchema as any).title
        ) {
          zodProp = (zodProp as any).describe((propSchema as any).title);
        }
        if (!required.includes(propName)) {
          zodProp = zodProp.optional();
        }
        shape[propName] = zodProp;
      }
      // если нет свойств вовсе, добавим искусственное опциональное поле, чтобы был properties
      if (Object.keys(shape).length === 0) {
        shape['_noop'] = z.string().optional().describe('no params');
      }
      return z.object(shape);
    }
    default:
      return z.any();
  }
};

const buildZodFromSchema = (schema: unknown): z.ZodObject<any> => {
  // Если не задано — создаём пустой объект с _noop
  if (
    !schema ||
    typeof schema !== 'object' ||
    Object.keys(schema as Record<string, unknown>).length === 0
  ) {
    return z.object({ _noop: z.string().optional().describe('no params') });
  }
  const s: any = schema;
  // Если это JSON Schema (есть type/properties/required) — конвертируем
  if (s.type || s.properties || Array.isArray(s.required)) {
    const zod = jsonSchemaToZod(s);
    // Гарантируем объект верхнего уровня
    return zod && zod._def?.typeName === 'ZodObject'
      ? (zod as z.ZodObject<any>)
      : z.object({ _noop: z.string().optional() });
  }
  // Иначе поддерживаем «плоский» формат: { key: "Описание" | zodType }
  const entries = Object.entries(s as Record<string, unknown>).map(
    ([key, value]) => [
      key as string,
      typeof value === 'string'
        ? z.string().describe(value)
        : (value as z.ZodTypeAny)
    ]
  );
  const shape: Record<string, z.ZodTypeAny> = {} as Record<
    string,
    z.ZodTypeAny
  >;
  for (const [k, v] of entries as Array<[string, z.ZodTypeAny]>)
    shape[k] = v || z.any();
  return z.object(shape);
};
