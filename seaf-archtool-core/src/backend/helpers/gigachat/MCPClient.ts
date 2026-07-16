import { Client } from '@modelcontextprotocol/sdk/client';
import { SSEClientTransport } from '@modelcontextprotocol/sdk/client/sse';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp';

import { MCPClientInterface, MCPConfig, MCPTrasport } from '@global/MCP/types';
import { Tool } from '@modelcontextprotocol/sdk/types';

import { getLoggerWithTag } from '@global/logger/v2/logger.mjs';
const logger = getLoggerWithTag('MCPClient');

const MAX_ERROR_COUNT = 3;

export class MCPClient implements MCPClientInterface {
  mcpServerUrl: URL;
  transportType: MCPTrasport;
  clientID: string;
  private client: Client | null;
  errorCount: number;
  isConnected: boolean;

  constructor(config: MCPConfig, clientID: string) {
    this.mcpServerUrl = config.url;
    this.transportType = config.transport;
    this.clientID = clientID;
    this.client = null;
    this.errorCount = 0;
    this.isConnected = false;
  }

  async connect() {
    if (this.client) {
      return;
    }

    const transport = this.createTransport();
    const client = new Client({ name: this.clientID, version: '1.0.0' });
    this.registerCallback(client);
    await client.connect(transport);
    this.client = client;
    this.isConnected = true;
  }

  async getTools(
    // eslint-disable-next-line no-unused-vars
    mcpConfig: MCPConfig
  ) {
    if (!this.client) {
      await this.connect();
    }
    const listTools = await this.client.listTools();
    if (Array.isArray(listTools?.tools)) {
      return listTools.tools;
    } else {
      throw new Error(
        `MCP-клиент ${this.clientID}. Ошибка при получении списка тулов!`
      );
    }
  }

  private registerCallback(client) {
    client.onerror = async(e) => {
      logger.debug(
        () => `MCP-клиент ${this.clientID}. Ошибка при выполнении: ${e.message}`
      );
      this.errorCount++;
      if (this.errorCount > MAX_ERROR_COUNT) {
        client.close();
      }
    };
    client.onclose = () => {
      logger.debug(() => `MCP-клиент ${this.clientID}. Соединение закрыто!`);
      this.isConnected = false;
    };
  }

  private createTransport() {
    let ClientTransport;
    if (this.transportType === MCPTrasport.sse) {
      ClientTransport = SSEClientTransport;
    } else if (this.transportType === MCPTrasport.streamableHttp) {
      ClientTransport = StreamableHTTPClientTransport;
    } else {
      throw new Error(
        `MCP-клиент ${this.clientID}. Ошибка при создании транспорта - указан некорректный тип: ${this.transportType}`
      );
    }
    return new ClientTransport(this.mcpServerUrl);
  }

  async callTool(
    _mcpConfig: MCPConfig,
    name: Tool['name'],
    args: string | Record<string, unknown>
  ): Promise<ReturnType<Client['callTool']>> {
    return await this.client.callTool({
      name,
      arguments: args
    });
  }
}
