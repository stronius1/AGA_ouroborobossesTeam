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
  limitations under the License.

  Maintainers:
    Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2026

  Contributors:
    Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2026
*/

import { AiAgent } from '@global/gigachat/agent/AiAgent';
import { GigaChat, GigaChatClientConfig } from 'gigachat';
import { AgentType } from '@global/gigachat/agent/type/AgentType';
import { PullDataToolFn } from '@global/gigachat/agent/type/PullDataToolFn';
import { ContentChunk } from '@global/gigachat/agent/type/ContentChunk';
import { getLoggerWithTag } from '@global/logger/v2/logger.mjs';
import { GigachatSession, SessionSerializable } from '@global/gigachat/session/type/SessionSerializable';
import { Message, Usage } from 'gigachat/interfaces';
import { GigaChatTool } from '../type/SimpleAgentConfig';

import { MCPClientManager } from '@global/MCP/MCPClientManager';
import { mapMcpToolsToGigaChatFunctionSchemas } from '@global/MCP/helpers/mapMcpToolToGigaChatFunctionSchema';
import { RequestWithBenefits } from '@back/controllers/gigachat';
import { ToolManager } from '@global/gigachat/tools/ToolManager';
import { accumulateTokenCounter } from '@global/gigachat/helpers/accumulateTokenCounter';

const LOGGER_NAME = 'GigaChatAgent';
const logger = getLoggerWithTag(LOGGER_NAME);
const MAX_CONTEXT = 128000;

export class GigaChatAgent implements AiAgent {
  gigachat: GigaChat;
  pullDataTool: PullDataToolFn;
  private mcpManager: MCPClientManager;
  private toolManager: ToolManager;

  constructor(
    gigachatConfig: GigaChatClientConfig,
    mcpManager: MCPClientManager,
    toolManager: ToolManager
  ) {
    this.gigachat = new GigaChat(gigachatConfig);
    this.mcpManager = mcpManager;
    this.toolManager = toolManager;
  }

  type: AgentType = 'gigachat';
  description = 'GigaChat';

  async fillNewChat(
      systemPrompt: string,
      sessionSerializable: SessionSerializable
  ): Promise<void> {
    this.pullDataTool = sessionSerializable.config.pullDataTool;
  }

  async *handleMessage(
    message: string,
    session: GigachatSession,
    request?: RequestWithBenefits
  ): AsyncIterable<ContentChunk> {
    const { content, tokens } = await this.startLoop(
      message,
      session,
      0,
      request
    );

    yield {
      content,
      tokens: {
        total: tokens.total_tokens,
        prompt: tokens.prompt_tokens,
        completion: tokens.completion_tokens
      }
    };
  }

  async startLoop(
    message: string,
    session: GigachatSession,
    deepCount: number,
    request?: RequestWithBenefits
  ): Promise<ContentChunk> {
    const tokenCounter: Usage = {
      completion_tokens: 0,
      prompt_tokens: 0,
      total_tokens: 0
    };

    if (this.shouldSummaryContext(session)) {
      logger.debug(() => `Session ${session.id}. Try to summary the context`);

      try {
        const { content, tokens } = await this.getSummaryContext(session);
        accumulateTokenCounter(tokenCounter, tokens);

        for (const tokenType in session.tokens) {
          session.tokens[tokenType] = 0; // TODO: ERA-2742 (Расчет токенов для контекста перед отправкой сообщения агенту)
        }
        session.messages.length = 1;

        session.messages.push({
          role: 'assistant',
          content: `[Сводка предыдущего диалога]:\n${content}`
        });

        logger.debug(
          () =>
            `Session ${session.id}. The context summary has been successfully completed.`
        );
      } catch (err) {
        logger.debug(
          () =>
            `Session ${session.id}. An error occurred when trying to summary the context!`,
          err
        );
      }
    }
    
    session.messages.push({ role: 'user', content: message });

    const tools = (
      Array.isArray(session.config.tools) ? session.config.tools : []
    ) as GigaChatTool[];

    const functionSchema = tools
      .map((toolConfig) => {
        const schema = this.toolManager.getToolSchema(toolConfig);
        if(!schema) {
          logger.warn(() => `Session ${session.id}. Schema not filled by tool config:\n${JSON.stringify(toolConfig)}`);
        }
        return schema;
      })
      .filter(Boolean);
    
    const mcpServersConfig = session.config?.mcpServers;
    if(Array.isArray(mcpServersConfig)) {
      const mcpTools = await this.mcpManager.getTools(mcpServersConfig);
      const mcpFunctionSchema = mapMcpToolsToGigaChatFunctionSchemas(mcpTools);

      logger.debug(
        () =>
          `Session ${session.id}. MCP functions added: ${mcpFunctionSchema.length}.`
      );
      
      functionSchema.push(...mcpFunctionSchema);
    }

    const subagents = session.config?.subagents;
    if(subagents) {
      const subagentsSchemas = subagents.map((subagent) => subagent?.schema);
      functionSchema.push(...subagentsSchemas);
    }

    logger.debug(
      () =>
        `Session ${session.id}. Functions registered: ${functionSchema.length}. Messages: ${session.messages.length}.`
    );

    let executeCount = 0;
    let executeToolCount = 0;
    const messagesBeforeLoop = session.messages.length;

    let isRequestToApiRequired = true;

    logger.debug(
      () => `Session ${session.id}. Loop started. Messages: ${messagesBeforeLoop}`
    );

    const sessionConfig = session.config as any;

    while (isRequestToApiRequired) {
      const response = await this.execute({
        messages: session.messages,
        functionSchema,
        executeCount: ++executeCount,
        sessionId: session.id,
        sessionConfig
      }).catch(err => {
        if (err?.message === '[object Object]') {
          err.message =
            err?.response?.statusText ||
            err?.response?.data?.message ||
            err?.response?.status ||
            err?.response?.data?.status ||
            err.message;
        }
        throw err;
      });

      accumulateTokenCounter(tokenCounter, response.usage);

      const choice = response.choices[0];

      session.messages.push(choice.message);

      if (choice.finish_reason === 'stop') {
        break;
      }

      if (choice.message.function_call) {
        const { name, arguments: args } = choice.message.function_call;

        const toolConfig = (session.config.tools || []).find(
          (tool) => tool?.schema?.name === name || tool?.type === name
        ) as any;

        executeToolCount += 1;

        const message: Message = {
          name,
          role: 'function'
        };

        try {
          logger.debug(
            () =>
              `Session ${session.id}. Execute tool #${executeToolCount} (${name}).\nTool config:\n${
                typeof toolConfig === 'string'
                  ? toolConfig
                  : JSON.stringify(toolConfig)
              }.\nArguments:\n${
                typeof args === 'string' ? args : JSON.stringify(args)
              }`
          );

          const subagent = Array.isArray(subagents) && subagents.find(({id}) => name === id);

          let functionResult;
          const toolType = subagent 
            ? 'subagent'
            : (this.mcpManager && this.mcpManager.checkIsMCPTool(name))
              ? 'mcp'
              : 'default';

          if (toolType === 'subagent') {
            if(deepCount > 1) {
              throw new Error('Недопустима зависимость между субагентами');
            }

            const message = args.request;
            if(!message) {
              throw new Error('Не сформирован запрос для субагента');
            }

            const subSession = {
              config: subagent.config,
              id: session.id,
              tokens: session.tokens,
              messages: [{'role': 'system', content: subagent.systemPrompt}]
            };

            const { content, tokens } = await this.startLoop(message, subSession, deepCount + 1, request);
            accumulateTokenCounter(tokenCounter, tokens);

            functionResult = content;

          } else if (this.mcpManager && this.mcpManager.checkIsMCPTool(name)) {
            functionResult = await this.mcpManager.callTool(name, args);

          } else if (toolType === 'default') {
            functionResult = await this.toolManager.callTool(
              name, 
              args, 
              toolConfig, 
              sessionConfig,
              session.id, 
              request
            );

          } else {
            throw new Error('Не удалось определить инструмент (tool) для выполнения!');
          }

          if (!functionResult) {
            throw new Error(`Функция ${name} ничего не вернула`);
          }

          Object.assign(message, {
            content: JSON.stringify(functionResult)
          });
        } catch (e) {
          logger.error(
            () =>
              `Session ${session.id}. Execute tool #${executeToolCount} (${name}) failed!`,
            e
          );

          Object.assign(message, {
            content: JSON.stringify({
              function_call: {
                status: 'error',
                error_message: `Ошибка при выполнении функции ${name}`
              }
            })
          });
        }

        session.messages.push(message);
      } else {
        isRequestToApiRequired = false;
      }
    }

    const totalMessages = session.messages.length;

    logger.debug(
      () =>
        `Session ${session.id}. Loop is done! Total messages: ${totalMessages}. New messages: ${
          totalMessages - messagesBeforeLoop
        }`
    );

    const { content } = session.messages.at(-1);

    return { content, tokens: tokenCounter };
  }
  
  // eslint-disable-next-line no-unused-vars
  async endChat(session: SessionSerializable): Promise<void> {
  }

  private async execute({ messages, functionSchema, executeCount, sessionId, sessionConfig }) {
    logger.debug(
      () =>
        `Session ${sessionId}. Request to GigaChat API #${executeCount}. Messages: ${messages.length}`
    );

    const response = await this.gigachat.chat({
      model: sessionConfig?.model,
      functions: functionSchema,
      messages: messages,
      function_call: functionSchema.length > 0 ? 'auto' : 'none'
    });

    logger.debug(
      () =>
        `Session ${sessionId}. The response was received successfull:\n${JSON.stringify(
          response
        )}`
    );

    return response;
  }

  private shouldSummaryContext(session) {
    return session.tokens.prompt > 0.8 * MAX_CONTEXT;
  }

  private async getSummaryContext(session: GigachatSession) {
    const message = session.messages
      .slice(1)
      .map(({ role, content }) => {
        if (!(role === 'assistant' || role === 'user')) {
          return null;
        }
        return `[${role}]: ${content}`;
      })
      .filter(Boolean)
      .join('\n\n');

    const messages: Message[] = [
      {
        role: 'system',
        content: `
        Ты — ассистент по сжатию контекста диалога.
        Суммаризируй переписку ниже, сохранив:
        - ключевые факты и решения;
        - имена сущностей, числа, ссылки;
        - незавершённые задачи и открытые вопросы;
        - результаты вызовов инструментов (кратко).

        Не добавляй новую информацию. Ответ — только сводка на русском языке.`
      },
      { role: 'user', content: message }
    ];

    const response = await this.gigachat.chat({
      model: session?.config?.model,
      messages: messages
    });

    logger.debug(
      () =>
        `Session ${session.id}. The context summary has been successfully completed.`
    );

    return {
      content: response.choices[0].message.content,
      tokens: response.usage
    };
  }
}
