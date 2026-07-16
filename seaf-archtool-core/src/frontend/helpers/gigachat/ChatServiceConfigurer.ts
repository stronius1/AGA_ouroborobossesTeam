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
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2026
*/

import {ChatService} from '@global/gigachat/ChatService';
import {BrowserAiSessionStorageImpl} from '@front/helpers/gigachat/BrowserAiSessionStorageImpl';
import {gigachatOptions} from './GigachatOptionsHelper';
import {AiChatLimits, ChatServiceImpl} from '@global/gigachat/ChatServiceImpl';
import env from '@front/helpers/env';
import ChatServiceProxy from '@front/helpers/gigachat/ChatServiceProxy';
import {GigaChatAgent} from '@global/gigachat/agent/GigaChatAgent/GigaChatAgent';
import {MCPClientManager} from '@global/MCP/MCPClientManager';
import {MCPClient} from './MCPClient';
import {ToolManager} from '@global/gigachat/tools/ToolManager';
import {JsonataTool} from '@global/gigachat/tools/JsonataTool';
import {jsonataToolCallback} from './tools/jsonataToolCallback';
import {PutContentTool} from '@global/gigachat/tools/PutContentTool/PutContentTool';
import {putContentToolCallback} from './tools/putContentToolCallback';
import {putContentPluginSchema} from '@global/gigachat/tools/PutContentTool/schemas';

export const chatService = async(): Promise<ChatService> => {
  if (env.isBackendMode) {
    return new ChatServiceProxy();
  } else if (env.isPlugin()) {
    const sessionManager = new BrowserAiSessionStorageImpl();
    const aiChatLimits: AiChatLimits = {
      maxMsgInHistory: env.gigachatMaxMsgInHistory,
      maxSumSymbolOfAllMsg: env.gigachatMaxSumSymbolOfAllMsg
    };
    const gigaChatClientConfig = await gigachatOptions();
    // Во фронтовом (непортальном) режиме запрещаем react-агента
    const service = new ChatServiceImpl(sessionManager, gigaChatClientConfig, ['simple', 'gigachat'], aiChatLimits);

    const toolManager = new ToolManager();
    toolManager.registerTool(new JsonataTool(jsonataToolCallback));
    toolManager.registerTool(new PutContentTool(putContentToolCallback, putContentPluginSchema));

    service.registerAgent(new GigaChatAgent(gigaChatClientConfig, new MCPClientManager(MCPClient), toolManager));
    return service;
  }
};
