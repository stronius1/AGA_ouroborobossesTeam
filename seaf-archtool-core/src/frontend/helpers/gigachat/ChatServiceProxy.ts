import { ChatService } from '@global/gigachat/ChatService';
import { AgentEntry } from '@global/gigachat/agent/type/AgentEntry';
import { ContentChunk } from '@global/gigachat/agent/type/ContentChunk';
import { AgentConfig } from '@global/gigachat/agent/type/AgentConfig';
import env from '@front/helpers/env';
import EventSourceStream from '@server-sent-stream/web';
import { v4 as uuidv4 } from 'uuid';
import { HttpHeaders } from '@global/helpers/httpHeaders.mjs';
import axios from 'axios';
import userStore from '@front/store/userStore';
import { extreactOrgCtxFromWindow } from '@front/helpers/orgCtxTools';

export default class ChatServiceProxy implements ChatService {
  async getAgentsList(): Promise<AgentEntry[]> {
    const response = await axios<any, AgentEntry[]>({
      method: 'GET',
      url: env.backendURL + '/seaf-core/api/new/chat/agents'
    });
    if (response.status !== 200) {
      throw new Error(`[ChatServiceProxy.startChat] Response status: ${response.status}`);
    }
    return response.data;
  }

  async startChat(systemPrompt: string, type: string, config: AgentConfig, sessionId?: string): Promise<string> {
    const data = {
      systemPrompt,
      type,
      config,
      sessionId
    };
    const response = await axios<any, Record<'sessionId', string>>({
      method: 'POST',
      url: env.backendURL + '/seaf-core/api/new/chat/start',
      headers: {
        'Content-Type': 'application/json'
      },
      data
    });
    if (response.status !== 200) {
      throw new Error(`[ChatServiceProxy.startChat] Response status: ${response.status}`);
    }
    return response.data.sessionId;
  }

  async* message(message: string, sessionId: string): AsyncIterable<ContentChunk> {
    const data = {
      message,
      sessionId
    };
    const headers = {
        'Content-Type': 'application/json',
        [HttpHeaders.REQUEST_ID]: uuidv4()
    };
    const orgCtx = extreactOrgCtxFromWindow();
    if (orgCtx) {
      Object.assign(headers, { [HttpHeaders.X_SFA_ORGCTX]: orgCtx});
    }
    const accessToken = await userStore.getAccessToken();
    if(accessToken) {
      Object.assign(headers, { 'Authorization': 'Bearer ' + accessToken });
    }
    const response = await fetch(env.backendURL + '/seaf-core/api/new/chat/message', {
      method: 'POST',
      headers,
      body: JSON.stringify(data)
    });
    if (!response.ok) {
      throw new Error(`[ChatServiceProxy.message] Response status: ${response.status}`);
    }
    const decoder = new EventSourceStream();
    const reader = response.body.pipeThrough(decoder).getReader();
    while (true) {
      const {done, value} = await reader.read();
      if (done || value.data === '[DONE]') break;
      const parse = JSON.parse(value.data) as ContentChunk;
      yield parse;
    }
  }

  async endChat(sessionId: string): Promise<void> {
    const data = {
      sessionId
    };
    const response = await axios({
      method: 'POST',
      url: env.backendURL + '/seaf-core/api/new/chat/end',
      headers: {
        'Content-Type': 'application/json'
      },
      data
    });
    if (response.status !== 200) {
      throw new Error(`[ChatServiceProxy.endChat] Response status: ${response.status}`);
    }
  }
}
