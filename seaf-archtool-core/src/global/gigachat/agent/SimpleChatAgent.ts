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
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2026
*/

import {AiAgent} from '@global/gigachat/agent/AiAgent';
import {GigaChat, GigaChatClientConfig} from 'gigachat';
import {AgentType} from '@global/gigachat/agent/type/AgentType';
import {PullDataToolFn} from '@global/gigachat/agent/type/PullDataToolFn';
import {ContentChunk} from '@global/gigachat/agent/type/ContentChunk';
import {Chat} from 'gigachat/interfaces';
import {SimpleAgentConfig} from '@global/gigachat/agent/type/SimpleAgentConfig';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import {GigachatSession, SessionSerializable} from '../session/type/SessionSerializable';

const LOGGER_NAME = 'SimpleChatAgent';
const logger = getLoggerWithTag(LOGGER_NAME);

export class SimpleChatAgent implements AiAgent {
  gigachat: GigaChat;
  pullDataTool: PullDataToolFn;

  constructor(
      gigachatConfig: GigaChatClientConfig
  ) {
    this.gigachat = new GigaChat(gigachatConfig);
  }

  type: AgentType = 'simple';
  description = 'Простой RAG на GigaChat';

  async fillNewChat(
      systemPrompt: string,
      sessionSerializable: SessionSerializable
  ): Promise<void> {

    const { id, config } = sessionSerializable;

    this.pullDataTool = config.pullDataTool;
    if (config.jsonataQuery) {
      logger.debug(() => `Session ${id}. Trying to add context to the system prompt.`);

      const prompt = systemPrompt;
      systemPrompt = await this.enrichSystemPrompt(
          systemPrompt,
          config.jsonataQuery,
          this.pullDataTool,
          config.jsonataParams,
          config.jsonataOrigin,
          sessionSerializable
      );

      logger.debug(() => `Session ${id}. System prompt was updated: ${prompt !== systemPrompt}`);

      // Обновляем системный промпт в сессии
      sessionSerializable.messages[0].content = systemPrompt;
    }
  }

  async* handleMessage(message: string, session: SessionSerializable): AsyncIterable<ContentChunk> {
    const gigachatSession = session as GigachatSession;
    gigachatSession.messages.push({role: 'user', content: message});

    // Отправляем накопленные логи (если есть) при первом сообщении
    const pendingLogs = gigachatSession.pendingLogs;
    if (pendingLogs && pendingLogs.length > 0) {
      // Отправляем логи и очищаем их из сессии
      gigachatSession.pendingLogs = [];
      yield { logs: pendingLogs };
    }

    const agentConfig = gigachatSession.config as SimpleAgentConfig;
    const streamConfig: Chat = {
      messages: gigachatSession.messages,
      model: agentConfig.model,
      profanity_check: agentConfig.profanityCheck,
      temperature: agentConfig.temperature,
      top_p: agentConfig.topP,
      max_tokens: agentConfig.maxTokens,
      n: agentConfig.n,
      repetition_penalty: agentConfig.repetitionPenalty
    };

    let totalTokens = 0;
    let responseTokens = 0;
    let lastChunkWithTokens = null;
    let fullResponse = ''; // Накапливаем полный ответ

    logger.debug(() => `Session ${gigachatSession.id}. Request to GigaChat API.` );

    const stream =  this.gigachat.stream(streamConfig);
    for await (const chunk of stream) {
      const content = chunk?.choices[0].delta.content;

      // Накапливаем полный ответ вместо добавления каждого чанка как отдельное сообщение
      if (content) {
        fullResponse += content;
      }

      // Считаем токены из ответа (если доступно)
      if (chunk && 'usage' in chunk && chunk.usage) {
        totalTokens = (chunk.usage as any).total_tokens || 0;
        responseTokens = (chunk.usage as any).completion_tokens || 0;
        lastChunkWithTokens = chunk;
      }

      // Передаем токены только если это последний chunk с usage
      const tokens = (chunk && 'usage' in chunk && chunk.usage) ? {
        total: (chunk.usage as any).total_tokens || 0,
        prompt: (chunk.usage as any).prompt_tokens || 0,
        completion: (chunk.usage as any).completion_tokens || 0
      } : undefined;

      yield {content, tokens};
    }

    // После завершения стрима добавляем полный ответ в сессию как одно сообщение
    if (fullResponse) {
      gigachatSession.messages.push({role: 'assistant', content: fullResponse});
    }

    // Если токены были получены, отправляем их в последнем chunk'е
    if (lastChunkWithTokens && totalTokens > 0) {
      const finalTokens = {
        total: totalTokens,
        prompt: (lastChunkWithTokens.usage as any).prompt_tokens || 0,
        completion: responseTokens
      };
      logger.debug(() => `Session ${gigachatSession.id}. Sending final tokens to frontend: ${JSON.stringify(finalTokens)}.` );
      yield {tokens: finalTokens};
    } else {
      logger.debug(() => `Session ${gigachatSession.id}. No tokens to send - lastChunkWithTokens: ${!!lastChunkWithTokens}, totalTokens: ${totalTokens}.` );
    }

    // Логируем статистику токенов
    if (totalTokens > 0) {
      logger.debug(() => `Session ${gigachatSession.id}. GigaChat API response - Total tokens: ${totalTokens}, Response tokens: ${responseTokens}` );
    } else {
      logger.debug(() => `Session ${gigachatSession.id}. GigaChat API response completed (token count not available).` );
    }
  }

  async enrichSystemPrompt(
      systemPrompt: string,
      jsonataQuery: string,
      pullDataTool: PullDataToolFn,
      jsonataParams: any,
      jsonataOrigin: any,
      sessionSerializable: SessionSerializable
  ): Promise<string> {
    if (!jsonataQuery) return systemPrompt;
    try {

      const queryResponse = await pullDataTool(jsonataQuery, jsonataParams, jsonataOrigin);

      // Проверяем, возвращает ли pullDataTool объект с result и logs
      let queryResult: any;
      if (queryResponse && typeof queryResponse === 'object' && 'result' in queryResponse) {
        queryResult = queryResponse.result;
        // Сохраняем логи в сессии для отправки при первом сообщении
        if (queryResponse.logs && Array.isArray(queryResponse.logs) && sessionSerializable) {
          sessionSerializable.pendingLogs = queryResponse.logs;
        }
      } else {
        // Обратная совместимость: если возвращается просто результат
        queryResult = queryResponse;
      }

      return formatContextPrompt(systemPrompt, queryResult);
    } catch (error) {
      logger.error(() => `Session ${sessionSerializable.id}. Error executing JSONata query:`, error);
      return systemPrompt;
    }
  }

  // глушу предупреждение т.к. метод пока остается, но ничего не делает
  // eslint-disable-next-line no-unused-vars
  async endChat(session: SessionSerializable): Promise<void> {
  }
}

const formatContextPrompt = (systemPrompt, queryResult): string => {
  return `${systemPrompt}\n\nКонтекст, полученный из базы знаний:\n${JSON.stringify(queryResult, null, 2)}`;
};
