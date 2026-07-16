import { Function as GigaChatFunctionSchema } from 'gigachat/interfaces';
import { RequestWithBenefits } from '@back/controllers/gigachat';
import { DocumentConfigType } from './types/DocumentConfigType';
import { ToolConfigType } from './types/ToolConfigType';
import { ToolInterface } from './types/ToolInterface';
import { ToolTypes } from './types/ToolTypes';
import { getLoggerWithTag } from '@global/logger/v2/logger.mjs';

type ToolMap = Record<ToolTypes, ToolInterface>;

const DEFAULT_TOOL_TYPE = ToolTypes.jsonata;
const LOGGER_NAME = 'ToolManager';
const logger = getLoggerWithTag(LOGGER_NAME);

export class ToolManager {
  private tools: ToolMap;
  constructor() {
    this.tools = {} as ToolMap;
  }

  registerTool(tool: ToolInterface) {
    const { type } = tool;
    if (!this.tools[type]) {
      this.tools[type] = tool;
    } else {
      logger.warn(() => `Tool with type "${type}" already exist`);
    }
  }

  async callTool(
    name: string,
    args: any,
    toolConfig: any,
    sessionConfig: any,
    sessionId: string,
    request?: RequestWithBenefits
  ): Promise<unknown> {
    const validatedToolConfig = this.validateToolConfig(toolConfig);
    const validatedDocumentConfig = this.validateDocumentConfig(sessionConfig);
    const tool = this.tools[validatedToolConfig.type];

    return tool.execute(
      args,
      toolConfig,
      validatedDocumentConfig,
      sessionId,
      request
    );
  }

  getToolSchema(rawToolConfig: any): GigaChatFunctionSchema | undefined {
    try {
      const config = this.validateToolConfig(rawToolConfig);
      const schema = config?.schema ? config?.schema : this.tools?.[config.type]?.schema;
      if(schema && typeof schema === 'object') {
        return schema;
      }
      logger.warn(() => `Invalid tool schema: ${JSON.stringify(rawToolConfig)}`);
    } catch (e) {
      return;
    }
  }

  private validateToolConfig(rawToolConfig: any): ToolConfigType {
    if (!(rawToolConfig && typeof rawToolConfig === 'object')) {
      throw new Error('Invalid tool config format');
    }

    const toolType =
      typeof rawToolConfig?.type === 'string'
        ? rawToolConfig?.type
        : DEFAULT_TOOL_TYPE;

    if (!this.tools[toolType]) {
      throw new Error(
        `Tool with type "${rawToolConfig.type}" is not registered`
      );
    }

    const config = {
      type: toolType
    };

    if (rawToolConfig?.query) {
      Object.assign(config, { query: rawToolConfig?.query });
    }
    if (rawToolConfig?.schema) {
      Object.assign(config, { schema: rawToolConfig?.schema });
    }

    return config as ToolConfigType;
  }

  private validateDocumentConfig(sessionConfig: any): DocumentConfigType {
    const config: any = {};

    if (!(sessionConfig && typeof sessionConfig === 'object')) {
      return config;
    }

    const { jsonataOrigin: origin, jsonataParams: params, profile } = sessionConfig;

    if (origin && (typeof origin === 'string' || typeof origin === 'object')) {
      config.origin = origin;
    }
    if (params && typeof params === 'object') {
      config.params = params;
    }
    if(profile) {
      config.profile = profile;
    }

    return config;
  }
}
