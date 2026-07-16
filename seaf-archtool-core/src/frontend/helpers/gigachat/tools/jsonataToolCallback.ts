import { JSONataToolCallback } from '@global/gigachat/tools/JsonataTool';

import datasets from '@front/helpers/datasets';
import parser from '@global/manifest/parser3/index.mjs';

const dataProvider = datasets();

export const jsonataToolCallback: JSONataToolCallback = async(query, params = {}, origin) => {
  const manifest = parser.manifest;

  const result = await dataProvider.getData(
    manifest,
    {
      origin: origin,
      source: query
    },
    params
  );

  return result;
};
