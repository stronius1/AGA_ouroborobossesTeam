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
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber

  Contributors:
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
*/

import bitbucket from '@back/helpers/bitbucket.mjs';
import request from '@back/helpers/request.mjs';

export default async function requestBitBucketHash(source) {
    const driver = bitbucket;
    const path = source.split(':');
    const projectID = path[1];
    const repositoryId = path[2];
    const branchId = path[3].split('@')[0];
    const url = driver.branchInfo(projectID, repositoryId, branchId);
    const res = await request(url);
    const branch = res.data.values.find((b) => b?.displayId === branchId);
    if (!branch?.latestCommit) {
        throw new Error(`Ветка ${branchId} не найдена в удалённом репозитории.`);
    }
    return branch.latestCommit;
}
