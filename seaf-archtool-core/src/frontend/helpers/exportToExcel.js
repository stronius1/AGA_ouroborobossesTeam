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
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2025
*/

import env from '@front/helpers/env';

function base64(s) {
  return window.btoa(unescape(encodeURIComponent(s)));
}

function format(s, c) {
  return s.replace(/{(\w+)}/g, function(m, p) {
    return c[p];
  });
}

function onLoad(ctx) {
  const template =
    '<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel" xmlns="http://www.w3.org/TR/REC-html40"><head><!--[if gte mso 9]><xml><x:ExcelWorkbook><x:ExcelWorksheets><x:ExcelWorksheet><x:Name>{worksheet}</x:Name><x:WorksheetOptions><x:DisplayGridlines/></x:WorksheetOptions></x:ExcelWorksheet></x:ExcelWorksheets></x:ExcelWorkbook></xml><![endif]--><meta http-equiv="content-type" content="text/plain; charset=UTF-8"/></head><body><table>{table}</table></body></html>';

  if (env.isPlugin()) {
    window.$PAPI.download(
      format(template, ctx),
      'Экспорт в Excel',
      'Выберите файл для сохранения выгрузки',
      'xls'
    );
  } else {
    const link = document.createElement('a');
    link.download = `${ctx.worksheet}.xls`;
    link.href =
      'data:application/vnd.ms-excel;base64,' + base64(format(template, ctx));
    link.click();
  }
}

function htmlEscape(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\n/g, '&#10;');
}

export default function exportToExcel(headers, data = [], worksheetName) {
  const headerRow =
    '<tr>' +
    headers.map(({ value, text }) => `<th>${htmlEscape(text ?? value)}</th>`).join('') +
    '</tr>';

  const bodyRows = data
    .map((row) => {
      return (
        '<tr>' +
        headers
          .map(({ value }) => `<td style="vertical-align: top;" x:str="${htmlEscape(row[value] || '')}"></td>`)
          .join('') +
        '</tr>'
      );
    })
    .join('');

  const ctx = {
    worksheet: worksheetName || 'Worksheet',
    table: headerRow + bodyRows
  };

  onLoad(ctx);
}
