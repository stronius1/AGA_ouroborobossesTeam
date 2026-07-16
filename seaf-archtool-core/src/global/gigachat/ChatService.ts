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
*/

import {AgentConfig} from '@global/gigachat/agent/type/AgentConfig';
import {AgentEntry} from '@global/gigachat/agent/type/AgentEntry';
import {ContentChunk} from '@global/gigachat/agent/type/ContentChunk';
import {PullDataToolFn} from './agent/type/PullDataToolFn';
import {RequestWithBenefits} from '@back/controllers/gigachat';

export interface ChatService {
  startChat(systemPrompt: string, type: string, config: AgentConfig, sessionId?: string): Promise<string>;
  message(message: string, sessionId: string, pullData?: PullDataToolFn, request?: RequestWithBenefits): AsyncIterable<ContentChunk>;
  endChat(sessionId: string): Promise<void>;
  getAgentsList(): Promise<AgentEntry[]>;
}

