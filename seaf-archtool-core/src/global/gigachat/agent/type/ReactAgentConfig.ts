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
*/

import {PullDataToolFn} from '@global/gigachat/agent/type/PullDataToolFn';
import { Function as GigaChatToolSchema } from 'gigachat/interfaces';

export interface ReactToolDescriptor {
  name: string;
  description?: string;
  // Свободная схема параметров (ключи описаны строками, валидацию добавим позже)
  schema?: Record<string, unknown>;
  // JSONata запрос с шаблонами вида ${param}
  query: string;
  // Origin (датасеты) только для этого инструмента
  origin?: any;
}

export interface ReactAgentConfig {
  subagents?: Array<{
    systemPrompt: string,
    id: string,
    description: string,
    schema?: GigaChatToolSchema
    config: ReactAgentConfig
  }>,
  promptInjection?: string,
  params: {
    base: string              // base презентаций (profile.$base)
  },
  model?: string;
  temperature?: number;
  topP?: number;
  tools: ReactToolDescriptor[];
  // Для единообразия с simple-агентом оставляем возможность обогащения промпта
  jsonataQuery?: string;
  jsonataParams?: any;
  jsonataOrigin?: any;
  pullDataTool?: PullDataToolFn;
  history?: boolean;
}


