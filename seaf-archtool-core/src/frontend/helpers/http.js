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
      Navasardyan Suren, Sber - 2023
      R.Piontik <r.piontik@mail.ru> - 2023
*/

import errConstants from '@front/constants/errConstants.json';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

const logger = getLoggerWithTag('f/h/http');

export function errorMiddleware(params) {

	let error = null;

	if (params?.error) {
		switch (params.error.response?.status) {
          case 509:
            error = errConstants.SIZE_LIMIT;
            break;
          case 400:
            error = params.error.response?.data;
            break;
          default:
            error = errConstants.UNKNOWN;
		}
        logger.error(() => [{title: 'errorMiddleware', obj: params}]);
	}

	return { ...params, error };
}
