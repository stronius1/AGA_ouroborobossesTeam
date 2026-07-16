/*
  Copyright (C) 2026 Sber

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
      Alexander Romashin, Sber

  Contributors:
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2026
*/

import { PutContentToolCallback } from '@global/gigachat/tools/PutContentTool/PutContentTool';

import uriTool from '@front/helpers/uri';
import env from '@front/helpers/env';

export const putContentToolCallback: PutContentToolCallback = async(
  path,
  content,
  profile
) => {
  if(path.startsWith('/')) {
    path = path.split('/').filter(Boolean).join('/');
  }

  const basePath = profile?.base;
  const baseURI = basePath ? uriTool.getBaseURIOfPath(basePath) : env.rootManifest;
  const fullPath = uriTool.makeURIByBaseURI(path, baseURI);
  const result = await window.$PAPI.pushFile(fullPath, content);
  return result;
};
