import { Function as GigaChatToolSchema } from 'gigachat/interfaces';

export const subagentBaseSchema: Omit<
  GigaChatToolSchema,
  'name' | 'description'
> = {
  parameters: {
    type: 'object',
    properties: {
      request: {
        type: 'string',
        description:
          'Задача для субагента: что нужно сделать и какой результат ожидается'
      }
    },
    required: ['request']
  }
};
