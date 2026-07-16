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

export function checkRepositoryAPI(req, res, next) {
  const [protocol] = process.env.VUE_APP_DOCHUB_ROOT_MANIFEST?.split(':') ?? [];

  if (protocol === 'bitbucket') {
    next();
  } else {
    return res
      .status(404)
      .json({
        success: false,
        globalError: 'Данное API поддерживает только Bitbucket Open API'
      });
  }
}
