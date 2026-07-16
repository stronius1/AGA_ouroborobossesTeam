import { Function as GigaChatToolSchema } from 'gigachat/interfaces';
import { ToolInterface } from './types/ToolInterface';
import { ToolTypes } from './types/ToolTypes';
import { ToolConfigType } from './types/ToolConfigType';
import { RequestWithBenefits } from '@back/controllers/gigachat';
import { DocumentConfigType } from './types/DocumentConfigType';
import { getLoggerWithTag } from '@global/logger/v2/logger.mjs';

const LOGGER_NAME = 'JSONataTool';
const logger = getLoggerWithTag(LOGGER_NAME);

export type JSONataToolCallback = (
  query: string,
  params: Record<string, string>,
  origin?: string | Record<string, string>,
  options?: {
    storage: any,
    roleId: string | undefined
  }
) => Promise<unknown>;

export class JsonataTool implements ToolInterface {
  type: ToolTypes.jsonata;
  schema: GigaChatToolSchema;
  private callback: JSONataToolCallback;

  constructor(callback: JSONataToolCallback) {
    this.type = ToolTypes.jsonata;
    this.callback = callback;

    logger.debug(
      () => `JSONata tool registered with type: "${ToolTypes.jsonata}"`
    );
  }

  async execute(
    args: any,
    toolConfig: ToolConfigType,
    documentConfig: DocumentConfigType,
    sessionId: string,
    request?: RequestWithBenefits
  ) {
    const { params, origin } = documentConfig;

    const isCustomJsonata = toolConfig?.query && toolConfig?.schema;

    const jsonataExpression = isCustomJsonata ? toolConfig?.query : args?.query;

    let updatedParams;
    if (args && typeof args === 'object') {
      updatedParams = Object.assign({}, params, args);
    }

    if (
      !(typeof jsonataExpression === 'string' && jsonataExpression.length > 0)
    ) {
      throw new Error(`Invalid JSONata expression:\n${jsonataExpression}`);
    }

    let options;
    if(request && request.storage) {
      options = {
        storage: request.storage,
        roleId: request?.userProfile?.roleId
      };
    }

    const result = await this.callback(
      jsonataExpression,
      updatedParams,
      origin,
      options
    );

    return result;
  }
}
