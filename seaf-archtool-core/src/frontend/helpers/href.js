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

import env, {Plugins} from './env';
import routes from '@front/router/routes';
import uri from '@front/helpers/uri';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

const logger = getLoggerWithTag('/f/h/href');

function isLocalRoute(url) {
	logger.trace(() => `isLocalRoute? ${url}`);
	const urlRoot = url.pathname.split('/')[1];
	for (let i = 0; i < routes.length; i++) {
		const route = routes[i].path.split('/')[1];
		if (urlRoot === route) {
			logger.trace(() => [
				`isLocalRoute = true by urlRoot === route (${url})`,
				{title: 'urlRoot', obj: urlRoot},
				{title: 'route', obj: route}
			]);
			return true;
		}
	}
	logger.trace(() => `isLocalRoute = false | ${url}`);
	return false;
}

// Работа с ссылками
export default {
	// Переход по URL
	gotoURL(ref) {
		logger.trace(() => [
			`gotoURL ${ref}`,
			{title: 'window.location.href', obj: window.location.href}
		]);
		try {
			if (uri.isExternalURI(ref)) {
				logger.trace(() => `gotoURL: it is external URI [${ref}] move to blanc_`);
				window.open(ref, 'blank_');
			} else {
				logger.trace(() => `gotoURL: it is NOT external URI [${ref}]`);
				const url = new URL(ref, window.location);
				if (isLocalRoute(url)) {
					const pathname = url.pathname;
					const searchParams = Object.fromEntries(url.searchParams);
					const urlHash = url.hash;
					logger.trace(() => [
						`gotoURL: it is local route [${ref}], moved by params:`,
						{title: 'path', obj: pathname},
						{title: 'query', obj: searchParams},
						{title: 'hash', obj: urlHash}
					]);
					window.Router.push({
						path: pathname,
						query: searchParams,
						hash: urlHash
					});
				} else {
					logger.trace(() => `gotoURL: it is NOT local route [${ref}] move to blanc_`);
					window.open(url, 'blank_');
				}
			}
		} catch (e) {
			logger.error(() => `catch error when processing gotoUrl with ref ${ref}`, e);
			if (env.isPlugin(Plugins.idea)) {
				const pathAfterFirstHash = ref.split('#')[1];
				logger.trace(() => `after catch error with ref [${ref}], try push path [${pathAfterFirstHash}] to window router because we in jetbrains plugin`);
				window.Router.push({ path: pathAfterFirstHash});
			}
		}
	},
	// Обрабатывает клик по ссылке
	onClickRef(event) {
		event.preventDefault();
		logger.trace(() => 'onClickRef: invoke');
		if (event.shiftKey) {
			logger.trace(() => 'onClickRef: stop processing because shiftKey is pressed');
			return false;
		}
		const ref = event.currentTarget.href.baseVal || event.currentTarget.href;
		logger.trace(() => `onClickRef: processing ref ${ref}`);
		if (!ref.length) {
			logger.trace(() => `onClickRef: stop processing ref ${ref} because row length is null or 0`);
			return false;
		}
		this.gotoURL(ref);
		return false;
	},

	// Обрабатывает элемент для сормирование корректных ссылок в нем
	elProcessing(el) {
		const refs = el?.querySelectorAll && el.querySelectorAll('[href]') || [];
		for (let i = 0; i < refs.length; i++) {
            const ref = refs[i];
            if (!ref.hash) {
                ref.onclick = (event) => this.onClickRef(event);
            }
		}
	}
};
