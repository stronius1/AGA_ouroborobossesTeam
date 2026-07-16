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
      Alexander Romashin, Sber

  Contributors:
      Alexander Romashin, Sber - 2025
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2025
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2026
*/

import {AiSessionStorage} from '@global/gigachat/session/AiSessionStorage';
import {SessionConfig} from '@global/gigachat/session/type/SessionConfig';
import {SessionSerializable} from '@global/gigachat/session/type/SessionSerializable';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import {createSession} from '@global/gigachat/session/helpers/createSession';

const logger = getLoggerWithTag('b/g/s/PostgresAiSessionStorageImpl');

export class PostgresAiSessionStorageImpl implements AiSessionStorage {
  sessionRepository: any;
  constructor(sessionRepository) {
    this.sessionRepository = sessionRepository;
  }

  async create(config: SessionConfig): Promise<SessionSerializable | null> {
    if (typeof config === 'undefined') return null;
    const session = createSession(config);
    if (!session) return null;

    await this.sessionRepository.save(session);
    logger.debug(() => `Session created: ${session.id}`);
    return session;
  }

  async get(sessionId: string): Promise<SessionSerializable | null> {
    return await this.sessionRepository.getById(sessionId);
  }

  async invalidate(sessionId: string): Promise<void> {
    await this.sessionRepository.deleteById(sessionId);
  }

  async touch(sessionId: string): Promise<boolean> {
    return await this.sessionRepository.updateLastAccess(sessionId, Date.now());
  }

  async update(session: SessionSerializable): Promise<void> {
    session.lastAccess = Date.now();
    await this.sessionRepository.save(session);
  }
}
