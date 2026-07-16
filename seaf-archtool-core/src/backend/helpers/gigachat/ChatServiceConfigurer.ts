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

import {ChatService} from '@global/gigachat/ChatService';
import {gigachatOptions} from './GigachatOptionsHelper';
import {AiChatLimits, ChatServiceImpl} from '@global/gigachat/ChatServiceImpl';
import {LocalAiSessionStorageImpl} from '@back/gigachat/session/LocalAiSessionStorageImpl';
import {ReactChatAgent} from '@global/gigachat/agent/ReactChatAgent';
import {AiGenAChatAgent} from '@global/gigachat/agent/AIGenA/AIGenA';
import {PostgresAiSessionStorageImpl} from '@back/gigachat/session/PostgresAiSessionStorageImpl';
import GigachatSessionRepositoryPg from '@back/drivers/postgres/repository/GigachatSessionRepository';
import {getPgPool} from '@back/drivers/postgres/pool.mjs';
import {GIGACHAT_SESSION_TTL_MS} from '@back/helpers/env.mjs';
import {GIGACHAT_MAX_MESSAGE_COUNT_IN_HISTORY, GIGACHAT_MAX_SUM_SYMBOL_OF_ALL_MESSAGES} from '@back/helpers/env.mjs';
import {GigaChatAgent} from '@global/gigachat/agent/GigaChatAgent/GigaChatAgent';
import {MCPClientManager} from '@global/MCP/MCPClientManager';
import {MCPClient} from './MCPClient';
import {ToolManager} from '@global/gigachat/tools/ToolManager';
import {JsonataTool} from '@global/gigachat/tools/JsonataTool';
import {jsonataToolCallback} from './tools/jsonataToolCallback';
import {PutContentTool} from '@global/gigachat/tools/PutContentTool/PutContentTool';
import {putContentToolCallback} from './tools/putContentToolCallback';
import {putContentBackendSchema} from '@global/gigachat/tools/PutContentTool/schemas';
import {
  generateCanaryToken,
  validateCannaryTokenSymbolsPool,
  validateGigachatAgentCI
} from './canaryToken';

const canaryTokenSymbolsPool = process.env.VUE_APP_GIGACHAT_CANARY_TOKEN_POOL;
const gigachatAgentCI = process.env.VUE_APP_GIGACHAT_AGENT_CI;

let canaryToken: string | null = null;

// Должны быть указаны оба значения. Если заполнено хотя бы одно, считаем что у пользователя было намерение использовать токен.
if (canaryTokenSymbolsPool || gigachatAgentCI) {
  const tokensPoolValidateInfo = validateCannaryTokenSymbolsPool(
    canaryTokenSymbolsPool
  );
  const gigachatCIValidateInfo = validateGigachatAgentCI(gigachatAgentCI);

  if (tokensPoolValidateInfo.success && gigachatCIValidateInfo.success) {
    canaryToken = generateCanaryToken(
      gigachatAgentCI.slice(-8),
      canaryTokenSymbolsPool,
      4
    );
  } else {
    const errors = [tokensPoolValidateInfo, gigachatCIValidateInfo]
      .filter(({ success }) => !success)
      .map(({ error }) => `${error}\n`);

    throw new Error(`
        Ошибка в переменных окружения:
        ${errors}
        Заданные значения:
        VUE_APP_GIGACHAT_CANARY_TOKEN_POOL=${canaryTokenSymbolsPool}
        VUE_APP_GIGACHAT_AGENT_CI=${gigachatAgentCI}
      `);
  }
}

export const chatService = async(isCluster: boolean): Promise<ChatService> => {
  let sessionManager;
  if (isCluster) {
    const gigachatSessionRepositoryPg = new GigachatSessionRepositoryPg(getPgPool, GIGACHAT_SESSION_TTL_MS);
    sessionManager = new PostgresAiSessionStorageImpl(gigachatSessionRepositoryPg);
  } else {
    sessionManager = new LocalAiSessionStorageImpl(GIGACHAT_SESSION_TTL_MS);
  }
  const aiChatLimits: AiChatLimits = {
    maxMsgInHistory: GIGACHAT_MAX_MESSAGE_COUNT_IN_HISTORY,
    maxSumSymbolOfAllMsg: GIGACHAT_MAX_SUM_SYMBOL_OF_ALL_MESSAGES
  };
  const gigaChatClientConfig = await gigachatOptions();
  const service = new ChatServiceImpl(
    sessionManager,
    gigaChatClientConfig,
    ['simple', 'react', 'aigena', 'gigachat'],
    aiChatLimits,
    canaryToken
  );
  service.registerAgent(new ReactChatAgent(gigaChatClientConfig));
  service.registerAgent(new AiGenAChatAgent(gigaChatClientConfig));

  const toolManager = new ToolManager();
  toolManager.registerTool(new JsonataTool(jsonataToolCallback));
  toolManager.registerTool(new PutContentTool(putContentToolCallback, putContentBackendSchema));

  service.registerAgent(new GigaChatAgent(gigaChatClientConfig, new MCPClientManager(MCPClient), toolManager));
  return service;
};
