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
      Rostislav Kabalin <kabalin2009@yandex.ru> - 2022
*/

import env, { Plugins } from './env';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

const logger = getLoggerWithTag('f/h/clipboard');

function fallbackCopyTextToClipboard(text) {
	var textArea = document.createElement('textarea');
	textArea.value = text;

	// Avoid scrolling to bottom
	textArea.style.top = '0';
	textArea.style.left = '0';
	textArea.style.position = 'fixed';

	document.body.appendChild(textArea);
	textArea.focus();
	textArea.select();

	try {
		document.execCommand('copy');
	} catch (err) {
		logger.error(() => 'Fallback: Oops, unable to copy', err);
	}

	document.body.removeChild(textArea);
}

export default function(text)  {
	if (env.isPlugin(Plugins.idea)) {
		window.$PAPI.copyToClipboard(text);
	} else {
		if (!navigator.clipboard) {
			fallbackCopyTextToClipboard(text);
			return;
		}
		navigator.clipboard.writeText(text).then(
			// eslint-disable-next-line @typescript-eslint/no-empty-function
			function() {
			},
			function(err) {
				logger.error(() => 'Async: Could not copy text: ', err);
			}
		);
	}
}

