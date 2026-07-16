import { MCPConfig, MCPTrasport } from '../types';

export const validateMCPConfig = (config: any): {
  success: boolean,
  errors: Array<string>,
  config: MCPConfig
} => {
  const result = {
    success: false,
    errors: [],
    config: {} as MCPConfig
  };

  const transport = config?.transport;
  if (!MCPTrasport[transport]) {
    result.errors.push(`The configuration contains an incorrect type of mcp-server transport: ${transport}`);
  } else {
    result.config.transport = transport;
  }

  let url;
  try {
    url = new URL(config.url);
    if (url.pathname.length <= 1) {
      result.errors.push('MCP-server MUST provide a single HTTP endpoint path (hereafter referred to as the MCP endpoint) that supports both POST and GET methods. For example, this could be a URL like "https://example.com/mcp".');
    }
    result.config.url = url;
  } catch (e) {
    result.errors.push(`The configuration contains an incorrect mcp-server URL: ${config?.url}`);
  }

  if(result.errors.length === 0) {
    result.success = true;
  }

  return result;
};
