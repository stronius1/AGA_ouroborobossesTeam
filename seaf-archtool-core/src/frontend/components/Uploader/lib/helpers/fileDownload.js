/*
  Copyright (C) 2026 Sber

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

  Maintainers:
      Nikolay Temnyakov <temnjakovn@gmail.com>, Sber - 2026
*/

import env, { Plugins } from '@front/helpers/env';
import { getLoggerWithTag } from '@global/logger/v2/logger.mjs';

const logger = getLoggerWithTag('f/c/U/fileDownload');

function isIdeaPlugin() {
  return Boolean(env.isPlugin && env.isPlugin(Plugins.idea) && window.$PAPI);
}

function encodeBase64(uint8Array) {
  let binary = '';
  const chunk = 0x8000;

  for (let i = 0; i < uint8Array.length; i += chunk) {
    binary += String.fromCharCode.apply(null, uint8Array.subarray(i, i + chunk));
  }

  return btoa(binary);
}

export async function saveDownloadedFile(response, fileName = 'download.bin') {
  const normalizedFileName = fileName || 'download.bin';
  logger.debug?.(() => `Saving downloaded file, plugin=${isIdeaPlugin()}`);

  if (!response?.data) {
    throw new Error('Download response has no data');
  }

  if (isIdeaPlugin()) {
    if (!window?.$PAPI?.download) {
      throw new Error('Plugin download API is unavailable');
    }

    const blob = response.data;
    const mime = response.contentType || blob.type || 'application/octet-stream';
    const buffer = await blob.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    const base64 = encodeBase64(bytes);
    const extension = normalizedFileName.includes('.')
      ? normalizedFileName.split('.').pop()
      : '';

    await window.$PAPI.download(
      `data:${mime};base64,${base64}`,
      'Сохранение файла',
      'Скачивание файла из fileuploader',
      extension,
      normalizedFileName
    );
    return;
  }

  const href = URL.createObjectURL(response.data);
  try {
    const link = document.createElement('a');
    link.href = href;
    link.download = normalizedFileName;
    link.click();
  } finally {
    URL.revokeObjectURL(href);
  }
}
