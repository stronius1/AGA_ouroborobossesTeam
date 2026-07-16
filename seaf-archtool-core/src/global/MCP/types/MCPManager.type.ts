import { Tool } from '@modelcontextprotocol/sdk/types';
import { MCPClientInterface } from './MCPClientInterface';
import { MCPTrasport } from './MCPTrasport.type';

export type MCPClientID = string;
export type MCPToolName = Tool['name'];

export type MCPConfig = {
  url: URL;
  transport: MCPTrasport;
};

export type MCPClientData = {
  id: MCPClientID;
  client: MCPClientInterface;
  tools: Tool[];
  config: MCPConfig;
};

export type MaskedToolNameToClientMap = Record<string, MCPClientID>;
