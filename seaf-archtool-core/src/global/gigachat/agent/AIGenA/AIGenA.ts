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
    Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2025

  Contributors:
    Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2025
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2026
*/

import {GigachatSession, SessionSerializable} from '@global/gigachat/session/type/SessionSerializable';
import { RequestWithBenefits } from '@back/controllers/gigachat';
import { AiAgent } from '../AiAgent';
import { AgentType } from '../type/AgentType';
import { ContentChunk } from '../type/ContentChunk';
import { getLoggerWithTag } from '@global/logger/v2/logger.mjs';
import axios, { AxiosResponse } from 'axios';
import { GigaChatClientConfig } from 'gigachat';
import objectHash from 'object-hash';

type TMessageResponse = {
  messageID: string;
  chatID: string;
  msgText: string;
  parameters?: {
    type: string;
    guid: string;
    name: string;
  };
};

const SEAF_EMAIL = 'seaf@sber.ru';
const REQUEST_PATH = 'aiassist/sendMessage';
const AIGENA_AGENTS = {
  dzoStandards: 'dzo-standards'
};

const LOGGER_NAME = 'AIGenAChatAgent';
const logger = getLoggerWithTag(LOGGER_NAME);

export class AiGenAChatAgent implements AiAgent {
  type: AgentType = 'aigena';
  description = 'Взаимодействие с api ai-gena';

  config: GigaChatClientConfig;

  constructor(config: GigaChatClientConfig) {
    this.config = config;
  }

  async *handleMessage(
    message: string,
    session: SessionSerializable,
    request: RequestWithBenefits
  ): AsyncIterable<ContentChunk> {
    const gigachatSession = session as GigachatSession;

    const jwtToken = request?.tokenPayload?.payloadObj;
    if (!jwtToken) {
      throw new Error(
        `Session ${gigachatSession.id}. JWT not found. Authorization is required.`
      );
    }

    const missingProps = this.getMissingProps(jwtToken, [
      'sub',
      'empId',
      'surname',
      'name'
    ]);

    if (missingProps.length > 0) {
      throw new Error(
        `The token does not contain the required property. Missing properties: ${missingProps.join(
          ', '
        )}`
      );
    }

    const url = `${process.env.VUE_APP_AIGENA_API}/${REQUEST_PATH}`;
    const login = process.env?.VUE_APP_AIGENA_AUTH_LOGIN || '';
    const password = process.env?.VUE_APP_AIGENA_AUTH_PASSWORD ?? '';
    const token = Buffer.from(`${login}:${password}`).toString('base64');
    const headers = {
      'Content-Type': 'application/json; charset=utf-8',
      Authorization: `Basic ${token}`
    };

    const body = {
      email: jwtToken?.email ?? SEAF_EMAIL,
      msgText: message,
      agent: AIGENA_AGENTS.dzoStandards,
      created: Date.now(),
      aiGen: true,
      fromUserName: `${jwtToken.surname} ${jwtToken.name}`,
      preferred_username: jwtToken.sub,
      personalNumber: jwtToken.empId,
      from: objectHash({
        personalNumber: jwtToken.empId,
        preferred_username: jwtToken.sub
      })
    };

    if(typeof jwtToken?.patronymic === 'string') {
      body.fromUserName += ` ${jwtToken?.patronymic}`;
    }

    let isSuccessRequest = true;
    let content;
    try {
      logger.debug(
        () =>
          `Session ${gigachatSession.id}. Request to AIGenA API. Data:\n${JSON.stringify(
            body
          )}`
      );
      const response: AxiosResponse<TMessageResponse, any> = await axios({
        method: 'POST',
        headers,
        url,
        data: body,
        httpsAgent: this.config.httpsAgent
      });
      content = response.data.msgText;
    } catch (e) {
      logger.error(() => `Session ${gigachatSession.id}. Request to AIGenA failed:`, e);

      isSuccessRequest = false;
      content = `Произошла ошибка при отправке сообщения.\n${
        e?.message || e?.cause?.message || ''
      }`;
    }

    if (isSuccessRequest) {
      gigachatSession.messages.push({ role: 'user', content: message });
      gigachatSession.messages.push({ role: 'assistant', content });
    }

    yield { content };
  }

  // глушу предупреждение т.к. метод пока остается, но ничего не делает
  // eslint-disable-next-line no-unused-vars
  async endChat(session: SessionSerializable): Promise<void> {
  }

  private getMissingProps(
    token: Record<string, string>,
    requredProps: Array<string>
  ) {
    const missingProps = [];
    requredProps.forEach((prop) => {
      if (!token[prop]) {
        missingProps.push(prop);
      }
    });
    return missingProps;
  }
}
