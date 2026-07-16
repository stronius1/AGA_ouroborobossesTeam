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

export interface GigaChatTool {
  name: string;
  schema: Record<string, unknown>;
  query: string;
}

export type SimpleAgentConfig = {
  subagents?: Array<{
    systemPrompt: string,
    id: string,
    description: string,
    schema?: GigaChatToolSchema
    config: SimpleAgentConfig
  }>,
  promptInjection?: string,
  params: {
    base: string              // base презентаций (profile.$base)
  },
  jsonataQuery?: string,      // запрос, который используется для построения контекста в system prompt
  jsonataParams?: any,        // параметры, передаваемые в JSONata как $params
  jsonataOrigin?: any,        // origin презентаций (profile.origin / $base)
  pullDataTool: PullDataToolFn,
  model?: string,             // название модели, которое можно узнать методом https://gigachat.devices.sberbank.ru/api/v1/models
  profanityCheck?: boolean,   // цензура
  temperature?: number,       // Температура выборки в диапазоне от ноля до двух
  topP?: number,              // Вероятностная масса токенов в диапазоне от 0 до 1
  maxTokens?: number,         // Максимальное количество токенов, которые будут использованы для создания ответов
  n?: number,                 // Количество вариантов ответов, которые нужно сгенерировать для каждого входного сообщения
  repetitionPenalty?: number, // Допустимое количество повторений слов
  history?: boolean           // История сообщений
  tools?: GigaChatTool[]
}
