/*
  Copyright (C) 2021 owner Roman Piontik R.Piontik@mail.ru

  Copyright (C) 2022 Sber

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

  In any derivative products, you must retain the information of
  owner of the original code and provide clear attribution to the project

  https://dochub.info

  The use of this product or its derivatives for any purpose cannot be a secret.


  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.

  Maintainers:
      R.Piontik <r.piontik@mail.ru>

  Contributors:
      R.Piontik <r.piontik@mail.ru> - 2023
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2025
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber
*/

function hasParentheses(str) {
    const trimStr = str.trim();
    return trimStr.startsWith('(') && trimStr.endsWith(')');
}

export default {
    type(source, subject) {
        if (typeof source === 'string') {
            if (source.startsWith('source:')) {
                return 'resource-inline';
            } else if (hasParentheses(source)) {
                return 'jsonata-query';
            } else if (source.endsWith('.jsonata')) {
                return 'jsonata-file';
            } else if (source.endsWith('.yaml') && subject?.type === 'manifest') {
                return 'data-manifest';
            }
            
            let isURL;
            try {
                isURL = Boolean(new URL(source));
            } catch(e) {
                isURL = false;
            }
            if (isURL || source.endsWith('.yaml') || source.endsWith('.json') || source.endsWith('.xml')) {
                return 'data-file';
            }

            return 'id';
        } else if (typeof source === 'object') {
            return 'data-object';
        }
        return;
    }
};
