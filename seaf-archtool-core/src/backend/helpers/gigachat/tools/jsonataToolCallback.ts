import { JSONataToolCallback } from '@global/gigachat/tools/JsonataTool';

import datasets from '../../datasets.mjs';

export const jsonataToolCallback: JSONataToolCallback = async(query, params = {}, origin, options) => {
  const storage = options?.storage;
  const roleId = options?.roleId;

  const dataProvider = datasets(storage, roleId);
  const manifest = roleId ? storage.manifests[roleId] : storage.manifest;

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
