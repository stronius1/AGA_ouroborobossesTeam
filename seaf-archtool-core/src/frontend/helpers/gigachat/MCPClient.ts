import { MCPClientInterface, MCPConfig, MCPTrasport } from '@global/MCP/types';
import { Client } from '@modelcontextprotocol/sdk/client';
import { Tool } from '@modelcontextprotocol/sdk/types';

export class MCPClient implements MCPClientInterface {
  mcpServerUrl: URL;
  transportType: MCPTrasport;
  clientID: string;
  isConnected: boolean;

  constructor(config: MCPConfig, clientID: string) {
    this.mcpServerUrl = config.url;
    this.transportType = config.transport;
    this.clientID = clientID;
    this.isConnected = false;
  }

  async getTools(mcpConfig: MCPConfig): Promise<Tool[]> {
    return await window.$PAPI.toolList(mcpConfig);
  }
  async callTool(
    mcpConfig: MCPConfig,
    name: Tool['name'],
    args: string | Record<string, unknown>
  ): Promise<ReturnType<Client['callTool']>> {
    return await window.$PAPI.callTool(mcpConfig, name, args);
  }
}
