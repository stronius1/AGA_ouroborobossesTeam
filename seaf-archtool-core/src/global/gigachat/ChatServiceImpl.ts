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

import { ChatService } from '@global/gigachat/ChatService';
import { AgentConfig } from '@global/gigachat/agent/type/AgentConfig';
import { AiSessionStorage } from '@global/gigachat/session/AiSessionStorage';
import { AiAgent } from '@global/gigachat/agent/AiAgent';
import { SimpleChatAgent } from '@global/gigachat/agent/SimpleChatAgent';
import { AgentEntry } from '@global/gigachat/agent/type/AgentEntry';
import { AgentType } from '@global/gigachat/agent/type/AgentType';
import { ContentChunk } from '@global/gigachat/agent/type/ContentChunk';
import { getLoggerWithTag } from '@global/logger/v2/logger.mjs';
import { SessionMessage } from '@global/gigachat/session/type/SessionMessage';
import { GigaChatClientConfig } from 'gigachat';
import { SessionSerializable } from './session/type/SessionSerializable';
import { RequestWithBenefits } from '@back/controllers/gigachat';
import { HumanMessage } from '@langchain/core/messages';
import { subagentBaseSchema } from './subagents/subagentBaseSchema';
import { accumulateTokenCounter } from './helpers/accumulateTokenCounter';

const LOGGER_NAME = 'ChatService';
const logger = getLoggerWithTag(LOGGER_NAME);

export type AiChatLimits = {
  maxMsgInHistory: number;
  maxSumSymbolOfAllMsg: number;
};

export class ChatServiceImpl implements ChatService {
  sessionManager: AiSessionStorage;
  chatAgentsMap: Map<AgentType, AiAgent>;
  private readonly aiChatLimits: AiChatLimits;
  private readonly gigaChatClientConfig: GigaChatClientConfig;
  private readonly enabledAgents?: Set<AgentType>;
  private readonly canaryToken?: string | null;

  constructor(
    sessionManager: AiSessionStorage,
    gigaChatClientConfig: GigaChatClientConfig,
    enabledAgents: AgentType[],
    aiChatLimits: AiChatLimits,
    canaryToken?: string | null
  ) {
    this.sessionManager = sessionManager;
    this.gigaChatClientConfig = gigaChatClientConfig;
    this.canaryToken = canaryToken;
    this.enabledAgents = enabledAgents ? new Set(enabledAgents) : undefined;
    this.chatAgentsMap = new Map([
      ['simple', new SimpleChatAgent(gigaChatClientConfig)]
    ]);
    if (this.enabledAgents && !this.enabledAgents.has('simple')) {
      this.chatAgentsMap.delete('simple');
    }
    this.aiChatLimits = aiChatLimits;
    logger.info(
      () =>
        `ChatService run with limits. Max message in history: ${aiChatLimits.maxMsgInHistory}, max symbols in all messages: ${aiChatLimits.maxSumSymbolOfAllMsg}`
    );
  }

  registerAgent(agent: AiAgent): void {
    if (this.enabledAgents && !this.enabledAgents.has(agent.type)) return;
    this.chatAgentsMap.set(agent.type, agent);
  }

  async startChat(
    systemPrompt: string,
    type: string,
    config: AgentConfig,
    sessionId?: string
  ): Promise<string> {
    try {
      const agentType = type as AgentType;
      const agent = this.chatAgentsMap.get(agentType);
      if (!agent) {
        throw new Error(
          `Session ${sessionId}: Incorrect agent type "${type}" encountered`
        );
      }

      if (sessionId) {
        const sessionValid = await this.sessionManager.touch(sessionId);
        if (sessionValid) {
          logger.debug(() => `Session ${sessionId} exist just touch it`);
          return sessionId;
        } else {
          logger.debug(
            () => `Session ${sessionId} not exist exist, create new`
          );
        }
      }

      logger.debug(() => 'Starting new chat session with config:');
      logger.debug(() => `type: ${agentType}`);
      logger.debug(() => `config: ${JSON.stringify(config)}`);
      logger.debug(() => `systemPrompt:\n${systemPrompt}`);

      if (
        typeof systemPrompt === 'string' &&
        systemPrompt.trim().length > 0 &&
        this.canaryToken
      ) {
        systemPrompt = this.insertCanaryToken(systemPrompt);
        logger.debug(() => 'A canary token has been added to the systemPrompt');
      }
      
      if(Array.isArray(config?.subagents)) {
        config.subagents = config.subagents.map(subagentConfig => {
          const prompt = subagentConfig?.systemPrompt;
          const id = subagentConfig?.id;
          const config = subagentConfig?.config;
          const description = subagentConfig?.description;

          if(!prompt || !id || !config || !description) {
            logger.debug(
              () =>
                'Failed to initialize the agent. Check the "id" and "description" properties, as well as the configuration in the agent itself.'
            );
            return;
          }

          return {
            ...subagentConfig,
            systemPrompt: this.canaryToken ?  this.insertCanaryToken(prompt) : prompt,
            schema: {
              name: id,
              description,
              ...subagentBaseSchema
            },
            subagents: null
          };

        }).filter(Boolean);
      } else {
        config.subagents = null;
      }

      const session = await this.sessionManager.create({
        systemPrompt,
        type: agentType,
        agentConfig: config
      });
      if (typeof agent?.fillNewChat === 'function') {
        await agent.fillNewChat(systemPrompt, session);
        await this.sessionManager.update(session);
      }

      logger.debug(() => `Session ${session.id} was started!`);

      return session.id;
    } catch (e) {
      logger.error(() => `Error starting chat: ${e.message}`, e);
      throw e;
    }
  }

  async *message(
    message: string,
    sessionId: string,
    pullDataTool,
    request?: RequestWithBenefits
  ): AsyncIterable<ContentChunk> {
    try {
      if (!message || !sessionId) {
        const missingFields = [];
        if (!message) missingFields.push('message');
        if (!sessionId) missingFields.push('sessionId');
        throw new Error(`Missing required fields: ${missingFields.join(', ')}`);
      }

      const session = await this.sessionManager.get(sessionId);
      if (!session) {
        throw new Error(`Session ${sessionId} not found or expired.`);
      }

      if(!session.tokens) {
        session.tokens = {
            completion: 0,
            prompt: 0,
            total: 0
        };
      }

      const agent = this.chatAgentsMap.get(session.type);
      if (!agent) {
        throw new Error(`Agent for type '${session.type}' is not registered`);
      }

      if (!agent.pullDataTool && pullDataTool && session.config) {
        logger.debug(
          () =>
            `Session ${sessionId}. Tool function not found. A function has been assigned from the parameter for the tool.`
        );

        agent.pullDataTool = (...args) => {
          const [query, params, originArg] = args;
          return pullDataTool(query, params, originArg, session.config);
        };
      }

      logger.debug(
        () =>
          `Session ${sessionId}. Sending message through agent "${session.type}".`
      );

      const messagesLength = session.messages.length;
      const promptInjection = session?.config?.promptInjection;
      const updatedMessage = promptInjection ? this.injectUserPrompt(message, promptInjection) : message;

      if(this.canaryToken) {
        const accumulatedData = { content: '' };
        for await (const m of agent.handleMessage(updatedMessage, session, request)) {
          this.accumulateMessageContent(accumulatedData, m);
        }
        if(accumulatedData.content.includes(this.canaryToken)) {
          logger.warn(
            () =>
              `Session ${sessionId}. A canary token was found in the llm-response. An error message will be sent to the user. The dialog will be cleared.`
          );
          session.messages.length = 1;
          for(const tokenType in session.tokens) {
            session.tokens[tokenType] = 0;
          }
          await this.sessionManager.update(session);
          throw new Error('Техническая ошибка. Попробуйте позже.');
        } else {
          if(accumulatedData?.tokens) {
            accumulateTokenCounter(session.tokens, accumulatedData.tokens);
          }
          yield accumulatedData;
        }

      } else {
        for await (const m of agent.handleMessage(updatedMessage, session, request)) {
          if(m.tokens) {
            accumulateTokenCounter(session.tokens, m.tokens);
          }
          yield m;
        }
      }

      if(promptInjection && session.messages?.[messagesLength]) {
        if(session.type === 'react') {
          session.messages[messagesLength] = new HumanMessage(message);
        } else {
          session.messages[messagesLength].content = message;
        }
      }

      logger.debug(
        () => `Session ${sessionId}. The response was received successfully.`
      );

      session.messages = this.filterMessages(
        session,
        this.aiChatLimits
      ) as typeof session.messages;
      if(session?.config?.history !== false && session.messages.length > 1) {
        await this.sessionManager.update(session);
      }
    } catch (e) {
      logger.error(
        () => `Session ${sessionId}. Error when sending a message:\n`,
        e
      );

      const message = e?.message;
      const content = `Произошла ошибка при отправке сообщения:\n${message}`;

      yield { content };
    }
  }

  async endChat(sessionId: string): Promise<void> {
    const session = await this.sessionManager.get(sessionId);
    if (!session) {
      return;
    }
    const agent = this.chatAgentsMap.get(session.type);
    logger.debug(() => `Finishing chat session: ${sessionId}`);
    if (agent) {
      await agent.endChat(session);
    }
    await this.sessionManager.invalidate(sessionId);
  }

  async getAgentsList(): Promise<AgentEntry[]> {
    return Array.from(
      this.chatAgentsMap,
      ([type, agent]): AgentEntry => ({
        type: type,
        description: agent.description
      })
    );
  }

  /**
   * Фильтрует массив сообщений чата по двум лимитам
   * @returns {Array<SessionMessage>} - новый отфильтрованный массив
   */
  private filterMessages(
    session: SessionSerializable,
    aiChatLimits: AiChatLimits
  ): Array<SessionMessage> {
    if (!Array.isArray(session.messages) || session.messages.length === 0) {
      return [];
    }

    // Шаг 1: Применяем лимит на количество сообщений
    let filteredMessages = this.applyCountLimit(
      session,
      aiChatLimits.maxMsgInHistory
    );
    logger.debug(
      () =>
        `[${session.id}] After check message count limit (${aiChatLimits.maxMsgInHistory}), there are ${filteredMessages.length} messages left in the history`
    );

    // Шаг 2: Применяем лимит на суммарную длину строк
    filteredMessages = this.applyCharsLimit(
      session,
      aiChatLimits.maxSumSymbolOfAllMsg
    );
    logger.debug(
      () =>
        `[${session.id}] After checking the character limit (${aiChatLimits.maxSumSymbolOfAllMsg}), there are ${filteredMessages.length} messages left in the history`
    );
    return filteredMessages;
  }

  /**
   * Применяет лимит на количество сообщений
   * @private
   */
  private applyCountLimit(
    session: SessionSerializable,
    maxMessagesCount: number
  ): Array<SessionMessage> {
    if (session.messages.length <= maxMessagesCount) {
      logger.trace(() => `[${session.id}] There is no message limit exceeded`);
      return [...session.messages];
    }
    logger.trace(
      () =>
        `[${session.id}] Message limit exceeded, we'll leave only the system prompt and ${
          maxMessagesCount - 1
        } messages`
    );

    const systemMessage = session.messages[0];
    const otherMessages = session.messages.slice(1);

    // Оставляем системное сообщение и (countLimit - 1) последних сообщений
    const lastMessages = otherMessages.slice(-(maxMessagesCount - 1));

    return [systemMessage, ...lastMessages];
  }

  /**
   * Применяет лимит на суммарную длину строк
   * @private
   */
  private applyCharsLimit(
    session: SessionSerializable,
    maxAllMessagesLength: number
  ): Array<SessionMessage> {
    if (session.messages.length === 0) {
      logger.debug(
        () =>
          `[${session.id}] For the filter applyCharsLimit the message list is empty, this should not be the case, the system prompt should be`
      );
      return [];
    }

    const systemMessage = session.messages[0];
    const otherMessages = session.messages.slice(1);

    // Если даже системное сообщение превышает лимит, возвращаем только его
    const systemMessageLength = this.getMessageLength(systemMessage);
    if (systemMessageLength > maxAllMessagesLength) {
      logger.trace(
        () =>
          `[${session.id}] System prompt exceeds character limit for all messages (${maxAllMessagesLength}), but it cannot be deleted, we only return it`
      );
      return [systemMessage];
    }

    // Считаем оставшийся лимит после системного сообщения
    const remainingLimit = maxAllMessagesLength - systemMessageLength;
    logger.trace(
      () =>
        `[${session.id}] The system prompt takes ${systemMessageLength} characters, the total limit is ${maxAllMessagesLength}, the remainder is ${remainingLimit}`
    );

    // Проходим по сообщениям с конца (от самых новых к старым)
    // и собираем те, которые помещаются в лимит
    const messagesToKeep: Array<SessionMessage> = [];
    let totalLength = 0;

    for (let i = otherMessages.length - 1; i >= 0; i--) {
      const message = otherMessages[i];
      const messageLength = this.getMessageLength(message);

      // Если сообщение помещается в оставшийся лимит
      if (totalLength + messageLength <= remainingLimit) {
        logger.trace(
          () =>
            `[${session.id}] Message with index  [${i}] fits within the limit, we add it to the history`
        );
        messagesToKeep.push(message);
        totalLength += messageLength;
      } else {
        logger.trace(
          () =>
            `[${session.id}] Message with index [${i}] does not fit within the limit, we are deleting it from the history`
        );
        // Как только не помещается - прекращаем проверку,
        // так как более старые сообщения тоже не поместятся
        break;
      }
    }
    // Переворачиваем массив обратно и добавляем системное сообщение в начало
    return [systemMessage, ...messagesToKeep.reverse()];
  }

  /**
   * Получает длину сообщения (из поля content)
   * @private
   */
  private getMessageLength(message: SessionMessage): number {
    return message.content?.length || 0;
  }

  private accumulateMessageContent(acc, message: ContentChunk) {
    for(const key in message) {
      if(!message[key]) continue;

      if(key === 'content') {
        if(typeof message[key] !== 'string') continue;
        acc.content += message.content;
      } else {
        acc[key] = message[key];
      }
    }
  }

  private insertCanaryToken(prompt: string) {
    let result = '';
    for (let i = 0; i < prompt.length; i++) {
      result += prompt[i];

      if ((i + 1) % 15 === 0 && i !== prompt.length - 1) {
        result += this.canaryToken;
      }
    }
    return result;
  }

  private injectUserPrompt(userRequest, inject) {
    return `${inject}\n\n${userRequest}\n\n${inject}`;
  }
}
