import { DocumentConfigType } from './DocumentConfigType';
import { ToolConfigType } from './ToolConfigType';
import { ToolTypes } from './ToolTypes';
import { Function as GigaChatToolSchema } from 'gigachat/interfaces';

export interface ToolInterface {
  type: ToolTypes;
  schema?: GigaChatToolSchema;
  execute: (
    args: Record<string, any>,
    toolConfig: ToolConfigType,
    seafConfig: DocumentConfigType,
    sessionId: string,
    requestOptions: any
  ) => unknown;
}
