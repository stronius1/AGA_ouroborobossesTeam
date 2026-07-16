/*
  Copyright (C) 2023 Sber

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.

  Maintainers:
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber

  Contributors:
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2025
*/

import { sectionDeepLog } from './consts.mjs';

export const createChildPath = (path, key) => {
  return `${path === '/' ? '' : path}/${key}`;
};

export const checkIsObject = (object) => {
  return (
    Boolean(object) && !Array.isArray(object) && typeof object === 'object'
  );
};

export const getStorePath = (path) => {
  const structPath = (path || '/').split('/');
  const entityName = structPath[1];
  const deepSize = sectionDeepLog[entityName] ?? sectionDeepLog['$default$'];
  const storePath = structPath
    .slice(0, deepSize + 1)
    .join('/');

  return storePath;
};

export const getImportsDifferences = ({ new: newImports, old: oldImports }) => {
  const diff = [];

  [...newImports, ...oldImports].forEach((uri) => {
    const hasInNewImports = newImports.includes(uri);
    const hasInOldImports = oldImports.includes(uri);

    if (hasInNewImports && hasInOldImports) return null;

    diff.push({
      uri,
      action: hasInNewImports ? 'add' : 'remove'
    });
  });

  return diff;
};


export const createRepositoryIDfromURI = (uri) => {
  try {
    return uri.split('@')[0].split(':').slice(0, -1).join(':');
  } catch {
    throw new Error(`Repository path has an incorrect format: ${uri}`);
  }
};
