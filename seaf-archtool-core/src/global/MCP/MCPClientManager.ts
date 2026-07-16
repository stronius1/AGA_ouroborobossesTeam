import objectHash from 'object-hash';
import Ajv from 'ajv';

import { getLoggerWithTag } from '@global/logger/v2/logger.mjs';
import { validateMCPConfig } from './helpers/validateMCPConfig';

import {
  MCPClientConstructor,
  MaskedToolNameToClientMap,
  MCPClientData,
  MCPClientID,
  MCPConfig
} from './types';

const LOGGER_NAME = 'MCPManager';
const logger = getLoggerWithTag(LOGGER_NAME);

const SEPARATOR_SIGN_MASKED_TOOL_NAME = '.';

export class MCPClientManager {
  clients: Record<MCPClientID, MCPClientData>;
  toolNameToClientMap: MaskedToolNameToClientMap;
  private MCPClient: MCPClientConstructor;

  constructor(MCPClient: MCPClientConstructor) {
    this.MCPClient = MCPClient;
    this.clients = {};
    this.toolNameToClientMap = {};
  }

  removeClient(clientID) {
    const clientData = this.clients[clientID];
    if (!clientData) {
      return;
    }
    const { tools } = clientData;
    (tools ?? []).forEach(({ name }) => {
      delete this.toolNameToClientMap[name];
    });
    delete this.clients[clientID];
  }

  checkIsMCPTool(maskedToolName) {
    return Boolean(this.toolNameToClientMap[maskedToolName]);
  }

  async getTools(configList: any[] = []) {
    const result = [];

    for (let i = 0; i < configList.length; i++) {
      const config = configList[i];

      const { success, errors, config: mcpConfig } = validateMCPConfig(config);

      if(!success) {
        logger.error(
          () => `Ошибки в конфигурации MCP-сервера:\n${errors.join('\n')}`
        );
        continue;
      }

      const clientID = this.createClientID(mcpConfig);

      if (this.clients[clientID]) {
        const { client, tools } = this.clients[clientID];

        if (client.isConnected) {
          result.push(...tools);
          continue;
        } else {
          this.removeClient(clientID);
        }
      }

      try {
        const client = new this.MCPClient(mcpConfig, clientID);
        const tools = await client.getTools(mcpConfig);

        const maskedTools = tools.map((tool) => ({
          ...tool,
          name: this.createMaskedToolName(tool.name, clientID)
        }));

        const map: MaskedToolNameToClientMap = maskedTools.reduce(
          (acc, tool) => {
            const maskedToolName = tool.name;
            return Object.assign(acc, { [maskedToolName]: clientID });
          },
          {}
        );
        Object.assign(this.toolNameToClientMap, map);

        const clientData: MCPClientData = {
          config: mcpConfig,
          client,
          tools: maskedTools,
          id: clientID
        };
        this.clients[clientID] = clientData;

        result.push(...maskedTools);
      } catch (e) {
        logger.error(
          () =>
            `MCP-клиент ${clientID}: Ошибка при инициализации: ${e.message}`,
          e
        );
      }
    }
    return result;
  }

  async callTool(maskedToolName, args) {
    const clientID = this.toolNameToClientMap[maskedToolName];
    if (!clientID) {
      throw new Error(`MCP-клиент ${clientID}: Клиент не найден!`);
    }

    const originToolName = this.getOriginToolName(maskedToolName);
    const { client, config, tools } = this.clients[clientID];

    const calledTool = tools.find(({ name }) => name === maskedToolName);
    if (!calledTool) {
      throw new Error(
        `MCP-клиент ${clientID}: Функция ${maskedToolName} не найдена!`
      );
    }

    const { inputSchema } = calledTool;
    if (!inputSchema) {
      throw new Error(
        `MCP-клиент ${clientID}: Схема функции ${maskedToolName} не найдена!`
      );
    }

    let parsedArgs: unknown;
    try {
      parsedArgs = typeof args === 'string' ? JSON.parse(args) : args;
    } catch (e) {
      throw new Error(
        `MCP-клиент ${clientID}: Некорректный JSON в аргументах инструмента ${maskedToolName}: ${e.message}! `
      );
    }

    const ajv = new Ajv({ allErrors: true, strict: false });
    const validate = ajv.compile(inputSchema);

    const isValid = validate(parsedArgs);
    if (!isValid) {
      const errorMessage = ajv.errorsText(validate.errors, {
        separator: '; '
      });
      throw new Error(
        `MCP-клиент ${clientID}: Аргументы инструмента "${maskedToolName}" не прошли валидацию: ${errorMessage}!`
      );
    }

    return await client.callTool(config, originToolName, args);
  }

  private createMaskedToolName(originName, clientID) {
    return `_${clientID}${SEPARATOR_SIGN_MASKED_TOOL_NAME}${originName}`;
  }

  private getOriginToolName(maskedToolName) {
    return maskedToolName
      .split(SEPARATOR_SIGN_MASKED_TOOL_NAME)
      .slice(1)
      .join(SEPARATOR_SIGN_MASKED_TOOL_NAME);
  }

  private createClientID(config: MCPConfig): MCPClientID {
    return objectHash({
      url: config.url.toString()
    });
  }
}
