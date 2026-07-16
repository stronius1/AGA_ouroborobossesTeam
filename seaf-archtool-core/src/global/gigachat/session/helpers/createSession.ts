import { v4 as uuid4 } from 'uuid';

import { SessionConfig } from '../type/SessionConfig';
import { GigachatSession, ReactSession } from '../type/SessionSerializable';
import { SystemMessage } from '@langchain/core/messages';

export const createSession = (
  config: SessionConfig
): ReactSession | GigachatSession | undefined => {
  const session = {
    id: uuid4(),
    config: config.agentConfig,
    created: Date.now(),
    lastAccess: Date.now()
  };

  const { type, systemPrompt } = config;

  if (type === 'react') {
    return Object.assign(session, {
      type,
      messages: [
        new SystemMessage(systemPrompt || '')
      ] as ReactSession['messages']
    }) as ReactSession;
  } else if (type === 'simple' || type === 'aigena' || type === 'gigachat') {
    return Object.assign(session, {
      type,
      messages: [
        { role: 'system', content: systemPrompt }
      ] as GigachatSession['messages']
    }) as GigachatSession;
  } else {
    throw new Error(`Invalid session type - ${config.type}`);
  }
};
