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
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
	  R.Piontik <r.piontik@mail.ru> - 2023
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2024
      Temnyakov Nikolay <temnjakovn@gmail.com>, Sber - 2024
*/

import validators from '../../global/rules/validators.mjs';
import datasets from './datasets.mjs';
import {loadValidatedConfigs} from '@back/helpers/configValidator.mjs';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';
import {isRolesMode} from '@back/utils/roles.mjs';

const LOG_TAG = 'validators';
const logger = getLoggerWithTag(LOG_TAG);

const waitForStackToClear = async(context) => {
	return new Promise((resolve) => {
		context.events.on('stackEmpty', () => {
			context.events.removeAllListeners('stackEmpty');
			resolve();
		});
		if(!context.stack.length) context.events.emit('stackEmpty');
	});
};

const configs = loadValidatedConfigs();

logger.trace(() => `Validated Configs: ${JSON.stringify(configs)}`);

// Выполняет валидаторы и накладывает исключения
export default async function(storage) {
	storage.problems = storage.problems || [];
	const pushValidator = (validator) => {
		storage.problems.push(validator);
	};
	//При включенной ролевой модели для валидации используем полный манифест в origin
	const storageManifest = isRolesMode() ? storage.manifests.origin : storage.manifest;
	logger.info(() => 'Executing validators...');
	const context = validators(datasets(storage), storageManifest, pushValidator, pushValidator, 0);

	await waitForStackToClear(context);
	logger.info(() => 'Done.');
}
