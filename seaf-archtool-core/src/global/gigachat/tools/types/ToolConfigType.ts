import { Function as GigaChatToolSchema } from 'gigachat/interfaces';
import { ToolTypes } from './ToolTypes';

export type ToolConfigType = {
  query?: string;
  type: ToolTypes;
  schema?: GigaChatToolSchema;
};
