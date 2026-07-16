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

import express, {Express, Request, Response} from 'express';
import {chatService} from '@back/helpers/gigachat/ChatServiceConfigurer';
import helpers from '@back/controllers/helpers.mjs';
import {ChatService} from '@global/gigachat/ChatService';
import {AgentType} from '@global/gigachat/agent/type/AgentType';
import {AgentConfig} from '@global/gigachat/agent/type/AgentConfig';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import { getPullDataTool } from '@back/helpers/gigachat/pullDataTool';

const logger = getLoggerWithTag('gigachat');

interface ExpressWithStorage extends Express {
  storage: any;
  isCluster: boolean
}

export interface RequestWithBenefits extends Request {
  storage: any;
  userProfile: {
    roleId?: string,
    userName: string,
    sub: string
  }
}

interface ChatStartParams {
  systemPrompt: string;
  type: AgentType;
  config: AgentConfig;
  sessionId: string;
}

interface ChatMessageParams {
  sessionId: string;
  message: string;
}

interface ChatEndParams {
  sessionId: string;
}

let chat: ChatService;

type reqHandlerFn = (req: RequestWithBenefits, res: Response) => Promise<void>;

const handleReq = async(app: ExpressWithStorage, req: RequestWithBenefits, res: Response, handler: reqHandlerFn) => {
  try {
    if (!helpers.isServiceReady(app, res)) return;
    await handler(req, res);
  } catch (error) {
    logger.error(() => 'Error handling request:', error);
    res.status(500).json({
      error: error.message
    });
  }
};

// Общий метод для стриминга ответа
const setupResponseStream = (res: Response) => {
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
};

// Метод для отправки чанка в стрим
const sendChunk = (res: Response, chunk: any) => {
  res.write(`data: ${JSON.stringify(chunk)}\n\n`);
};

// Метод для завершения стрима
const endStream = (res: Response) => {
  res.write('data: [DONE]\n\n');
  res.end();
};

export default async(app: ExpressWithStorage) => {
  chat = await chatService(app.isCluster);

  app.use(express.json());

  app.get(['/seaf-core/api/new/chat/agents', '/new/chat/agents'], async(req: Request, res: Response) => {
    try {
      res.json(await chat.getAgentsList());
    } catch (e) {
      res.status(500).json({
        error: e.message
      });
    }
  });

  app.post(['/seaf-core/api/new/chat/start', '/new/chat/start'], async(req: RequestWithBenefits, res: Response) => {
    await handleReq(app, req, res, async(req, res) => {
      const {systemPrompt, type, config, sessionId}: ChatStartParams = req.body;
      // pullDataTool принимает params как во фронтовых presentations
      logger.debug(() => `Start chat init tool. Has storage: ${Boolean(req.storage)}. Role: ${req?.userProfile?.roleId}. Storage hash: ${req.storage?.hash}`);
      config.pullDataTool = getPullDataTool(req.storage, req?.userProfile?.roleId, config);

      res.json({
        sessionId: await chat.startChat(systemPrompt, type, config, sessionId)
      });
    });
  });

  app.post(['/seaf-core/api/new/chat/message', '/new/chat/message'], async(req: RequestWithBenefits, res: Response) => {
    await handleReq(app, req, res, async(req, res) => {
      const {sessionId, message}: ChatMessageParams = req.body;
      logger.debug(() => `Message init tool. Has storage: ${Boolean(req.storage)}. Role: ${req?.userProfile?.roleId}. Storage hash: ${req.storage?.hash}`);
      const pullDataTool = getPullDataTool(req.storage, req?.userProfile?.roleId);
      
      setupResponseStream(res);
      const stream = chat.message(message, sessionId, pullDataTool, req);
      for await (const chunk of stream)
        sendChunk(res, chunk);
      endStream(res);
    });
  });

  app.post(['/seaf-core/api/new/chat/end', '/new/chat/end'], async(req: RequestWithBenefits, res: Response) => {
    await handleReq(app, req, res, async(req, res) => {
      const {sessionId}: ChatEndParams = req.body;
      await chat.endChat(sessionId);
      res.end();
    });
  });
};
