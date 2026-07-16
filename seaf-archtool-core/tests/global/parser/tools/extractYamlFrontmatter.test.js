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

import { extractFrontmatter } from '@global/manifest/tools/yamlHeader.mjs';

describe.skip('extractFrontmatter', () => {
  test('возвращает объект header и content при валидной YAML-шапке', () => {
    const input = `---
title: Документ
type: markdown
---
# Hello`;

    const result = extractFrontmatter(input);

    expect(result.header).toEqual({
      title: 'Документ',
      type: 'markdown'
    });
    expect(result.content).toBe('# Hello');
  });

  test('обрабатывает пустые строки перед frontmatter', () => {
    const input = `



---
title: Заголовок
---
# Контент`;

    const result = extractFrontmatter(input);

    expect(result.header).toEqual({ title: 'Заголовок' });
    expect(result.content).toBe('# Контент');
  });

  test('возвращает весь текст как content, если нет frontmatter', () => {
    const input = '# Без шапки\nСодержимое';

    const result = extractFrontmatter(input);

    expect(result.header).toBe(null);
    expect(result.content).toBe(input);
  });

  test('возвращает весь текст как content при невалидном YAML', () => {
    const input = `---
title: Невалидный: YAML: ---
# Markdown`;

    const result = extractFrontmatter(input);

    expect(result.header).toBe(null);
    expect(result.content).toBe(input);
  });

  test('работает, если после frontmatter пустая строка', () => {
    const input = `---
title: Заголовок
---

# H1`;

    const result = extractFrontmatter(input);

    expect(result.header).toEqual({ title: 'Заголовок' });
    expect(result.content).toBe('\n# H1');
  });

  test('обрабатывает markdown только с шапкой без контента', () => {
    const input = `---
title: Только шапка
---`;

    const result = extractFrontmatter(input);

    expect(result.header).toEqual({ title: 'Только шапка' });
    expect(result.content).toBe('');
  });

  test('обрабатывает вложенные поля в YAML', () => {
    const input = `---
meta:
  author: John
  version: 1.0
---
# Текст`;

    const result = extractFrontmatter(input);

    expect(result.header).toEqual({
      meta: { author: 'John', version: 1.0 }
    });
    expect(result.content).toBe('# Текст');
  });

  test('если yaml в середине файла, то это не считается шапкой', () => {
    const input = `
# Шапка yaml находится после этого markdown заголовка, а мы ждем только в начале, шапкой она не считается
---
meta:
  author: John
  version: 1.0
---
# Текст`;

    const result = extractFrontmatter(input);

    expect(result.header).toBe(null);
    expect(result.content).toBe(input);
  });

  test('если внутри markdown есть еще один yaml он не ломает парсинг шапки', () => {
    const input = `
---
meta:
  author: John
  version: 1.0
---
# Ниже какой-нибудь markdown который использует --- потому что ему надо, это не должно ломать работу с шапкой
\`\`\`
    ---
    meta:
      author: John
      version: 1.0
    ---
\`\`\`
`;

    const result = extractFrontmatter(input);

    expect(result.header).toEqual({
      meta: { author: 'John', version: 1.0 }
    });
    expect(result.content).toBe(`# Ниже какой-нибудь markdown который использует --- потому что ему надо, это не должно ломать работу с шапкой
\`\`\`
    ---
    meta:
      author: John
      version: 1.0
    ---
\`\`\`
`
    );
  });

  test('если нет шапки, то возвращаем просто контент', () => {
    const input = `
## Emphasis

**This is bold text**

__This is bold text__

*This is italic text*

_This is italic text_
`;

    const result = extractFrontmatter(input);

    expect(result.header).toBe(null);
    expect(result.content).toBe(input);
  });

  test('обрабатывает переносы строк Windows-стиля (\\r\\n)', () => {
    const input = '\r\n\r\n---\r\ntitle: Windows YAML\r\ntype: markdown\r\n---\r\n# Windows-style newline\r\n';

    const result = extractFrontmatter(input);

    expect(result.header).toEqual({
      title: 'Windows YAML',
      type: 'markdown'
    });

    expect(result.content).toBe('# Windows-style newline\r\n');
  });
});
