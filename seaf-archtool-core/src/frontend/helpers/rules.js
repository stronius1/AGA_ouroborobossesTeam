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
*/

import validators from '@global/rules/validators.mjs';
import datasets from './datasets';
import env from './env';
import requests from './requests';

// Выполняет валидаторы и накладывает исключения
export default function(manifest, success, reject) {
	if (env.isBackendMode) {
		requests.request('backend://problems/')
			.then((response) => {
				(response.data || []).map((item) => success(item));
			})
			.catch((error) => {
				reject(
					{
						id: '$system',
						title: 'Системные ошибки',
						error,
						items: [
							{
								uid: '$net',
								title: 'Не могу получить данные!',
								correction: 'Проверьте сетевое подключение и повторите попытку позже.',
								description: error.message
							}
						]
					}
				);
			});
	} else {
		return validators(datasets(), manifest, success, reject, 50);
	}
}
