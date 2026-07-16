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
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber

  Contributors:
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2026
*/

import {ROLES_MODE_V2_ENABLED} from '@back/helpers/env.mjs';
import {
    DEFAULT_ACCESS_WITHOUT_ROLE_MODEL_V2,
    DEFAULT_PERMISSION_WITHOUT_ROLE_MODEL_V2
} from '@back/cluster/constants.mjs';


/**
 * Определяем права пользователя и их уровень
 * Если ролевая модель V2 выключена то возвращаем дефолтное право и уровень
 * @returns {[{rp: string, ra: string}]|undefined} - список прав
 */
export function getPermissionWithAccess(req) {
    if (!ROLES_MODE_V2_ENABLED) {
        return [{rp: DEFAULT_PERMISSION_WITHOUT_ROLE_MODEL_V2, ra: DEFAULT_ACCESS_WITHOUT_ROLE_MODEL_V2}];
    } else {
        const { tokenPayload } = req;
        return tokenPayload?.payloadObj?.permissions?.map((value) => (
            {
                rp: value.rp?.toLowerCase(),
                ra: value.ra?.toLowerCase()
            }
        ));
    }
}
