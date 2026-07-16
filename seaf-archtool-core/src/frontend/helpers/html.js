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
      R.Piontik <r.piontik@mail.ru> - 2022
      Vladislav Nefedov <clay.zenx@gmail.com>, Sber - 2024
*/

// Обработка HTML
import query from '@front/manifest/query';
import env, {Plugins} from '@front/helpers/env';

export default {
	// Экранирование HTML
	escape(html) {
		return html.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;')
			.replace(/"/g, '&quot;')
			.replace(/'/g, '&#039;');
	},

  async collectLocationElement({expression, context, id, entity}) {
    // Здесь нужно рефачить, чтобы запросы в бэк ходили
    const result = await query.expression(expression)
      .evaluate(context) || [];

    if (env.isPlugin(Plugins.idea)) {
      return result.map((item) => ({
        title: item.title.slice(19),
        link: `${item.link}?entity=${entity}&id=${id}`
      }));
    }

    if (env.isPlugin(Plugins.vscode)) {
      return result.map((item) => ({
        title: item.title.replace('https://file+.vscode-resource.vscode-cdn.net', ''),
        link: `${item.link}?entity=${entity}&id=${id}`
      }));
    }

    return result;
  }
};

export function PrepareHTMLForPrint() {
  const printDoc = document;
  // Собираем все <script> теги из <head> и удаляем
  printDoc.head.querySelectorAll('script')
    .forEach((script) => script.remove());

  // Собираем шаблон для печати
  const content = printDoc.querySelector('.v-application__wrap');
  const html = `
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Print Content</title>
        ${printDoc.head.innerHTML}
    </head>
    <body>
        ${content ? content.outerHTML : 'No content available'}
    </body>
    </html>
  `;

  return html;
}

