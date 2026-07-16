import { Client } from '@modelcontextprotocol/sdk/client';
import { Tool } from '@modelcontextprotocol/sdk/types';
import { MCPTrasport } from './MCPTrasport.type';
import { MCPConfig } from './MCPManager.type';

export interface MCPClientInterface {
  mcpServerUrl: URL;
  transportType: MCPTrasport;
  clientID: string;
  isConnected: boolean;

  getTools(mcpConfig: MCPConfig): Promise<Tool[]>;
  callTool(
    mcpConfig: MCPConfig,
    name: Tool['name'],
    args: string | Record<string, unknown>
  ): Promise<ReturnType<Client['callTool']>>;
}

export type MCPClientConstructor = new (
  mcpConfig: MCPConfig,
  clientID: string,
) => MCPClientInterface;
