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

import {AiSessionStorage} from '@global/gigachat/session/AiSessionStorage';
import {SessionConfig} from '@global/gigachat/session/type/SessionConfig';
import {SessionSerializable} from '@global/gigachat/session/type/SessionSerializable';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import { createSession } from '@global/gigachat/session/helpers/createSession';

const LOGGER_NAME = 'LocalAiSessionStorageImpl';
const logger = getLoggerWithTag(LOGGER_NAME);

export class LocalAiSessionStorageImpl implements AiSessionStorage {
  private storage = new Map<string, string>();
  private readonly _sessionTtlMs: number;

  constructor(sessionTtlMs: number) {
    this._sessionTtlMs = sessionTtlMs;
  }

  async create(config: SessionConfig): Promise<SessionSerializable | null> {
    if (typeof config === 'undefined') return null;
    const session = createSession(config);
    if (!session) return null;
    this.storage.set(session.id, JSON.stringify(session));
    logger.debug(() => `Session created: ${session.id}`);
    return session;
  }

  async get(sessionId: string): Promise<SessionSerializable | null> {
    const rawSession = this.storage.get(sessionId);
    const session = JSON.parse(rawSession);
    if (session) {
      if (Date.now() - session.lastAccess > this._sessionTtlMs) {
        this.storage.delete(sessionId);
        logger.debug(() => `Session removed: ${sessionId}`);
        return null;
      }
      this.update(session);
      return session;
    } else {
      return null;
    }
  }

  async invalidate(sessionId: string): Promise<void> {
    this.storage.delete(sessionId);
  }

  async touch(sessionId: string): Promise<boolean> {
    const session = await this.get(sessionId);
    if (!session) {
      return false;
    } else {
      session.lastAccess = Date.now();
      await this.update(session);
      return true;
    }
  }

  async update(session: SessionSerializable): Promise<void> {
    session.lastAccess = Date.now();
    this.storage.set(session.id, JSON.stringify(session));
  }
}
