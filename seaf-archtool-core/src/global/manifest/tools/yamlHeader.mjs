/*
  Copyright (C) 2025 Sber

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
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025

  Contributors:
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
*/

import yaml from 'yaml';

/**
 * Регулярное выражение для извлечения YAML frontmatter из текста.
 *
 * ^\s* — допускаем любые пробелы или пустые строки до начала блока;
 * ---\r?\n — открывающий блок '---' с \n или \r\n;
 * ([\s\S]*?) — нежадный захват содержимого YAML-шапки;
 * \r?\n---\r?\n? — закрывающий блок с переносами в любых стилях.
 */
const FRONTMATTER_REGEX = /^\s*---\r?\n([\s\S]*?)\r?\n---\r?\n?/;

/**
 * Извлекает YAML frontmatter из строки.
 *
 * @param {string} text - Содержимое файла в виде строки.
 * @returns {{ header: object | null, content: string }}
 *
 * - Если frontmatter найден и корректен — `header` содержит объект, `content` — остальной текст документа.
 * - Если frontmatter не найден или невалиден — `header = null`, `content = весь файл`.
 */
export function extractFrontmatter(text) {
    const match = text.match(FRONTMATTER_REGEX);

    if (match) {
        const rawYaml = match[1];
        try {
            const parsed = yaml.parse(rawYaml);
            const content = text.slice(match[0].length);
            return { header: parsed, content: content };
        } catch (err) {
            // Ошибка парсинга YAML — считаем, что шапки нет
        }
    }

    return {
        header: null,
        content: text
    };
}
