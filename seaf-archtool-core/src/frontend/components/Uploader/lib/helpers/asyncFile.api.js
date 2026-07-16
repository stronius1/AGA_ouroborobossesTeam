/*
  Copyright (C) 2026 Sber

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
      Nikolay Temnyakov <temnjakovn@gmail.com>

  Contributors:
      Nikolay Temnyakov <temnjakovn@gmail.com>, Sber - 2026
*/

import env, { Plugins } from '@front/helpers/env';
import { v4 as uuidv4 } from 'uuid';

const API_BASE = '/api/v2';
const DEFAULT_PLUGIN_TIMEOUT_MS = 185_000;

function withTimeout(promise, timeoutMs, label) {
  if (!timeoutMs || timeoutMs <= 0) return promise;
  let timer;
  const timeoutPromise = new Promise((_, reject) => {
    timer = setTimeout(() => {
      reject(new Error(`${label || 'Plugin request'} timed out after ${timeoutMs}ms`));
    }, timeoutMs);
  });
  return Promise.race([promise, timeoutPromise]).finally(() => clearTimeout(timer));
}

function joinUrl(base, path) {
  const normalizedBase = String(base || '').replace(/\/$/, '');
  const normalizedPath = String(path || '').replace(/^\//, '');
  return `${normalizedBase}/${normalizedPath}`;
}

function apiUrl(path) {
  return joinUrl(env.s3CloudUrl || '', `${API_BASE}/${String(path || '').replace(/^\//, '')}`);
}

function isIdeaPlugin() {
  return Boolean(env.isPlugin && env.isPlugin(Plugins.idea) && window.$PAPI);
}

function safeDocumentTitle() {
  try {
    return document?.title || '';
  } catch (e) {
    return '';
  }
}

function normalizePageContext(pageContext = {}) {
  return {
    pageUrl: pageContext?.pageUrl ? String(pageContext.pageUrl) : '',
    pageObjectId: pageContext?.pageObjectId ? String(pageContext.pageObjectId) : '',
    pageTitle: pageContext?.pageTitle ? String(pageContext.pageTitle) : '',
    rowId: pageContext?.rowId != null ? String(pageContext.rowId) : ''
  };
}

export function buildCurrentPageContext() {
  let pageUrl = '';
  try {
    const href = window?.location?.href || '';
    const hash = window?.location?.hash || '';
    if (href && hash && !href.includes('#')) {
      pageUrl = href + hash;
    } else {
      pageUrl = href;
    }
  } catch (e) {
    pageUrl = '';
  }

  return {
    pageUrl,
    pageObjectId: '',
    pageTitle: safeDocumentTitle(),
    rowId: ''
  };
}

function withDefaultHeaders(headers = {}) {
  return {
    'X-Request-Id': uuidv4(),
    ...headers
  };
}

async function parseErrorResponseText(response) {
  try {
    return await response.text();
  } catch (e) {
    return '';
  }
}

function safeJsonParse(text, contextMessage = 'Invalid JSON response') {
  try {
    return JSON.parse(text);
  } catch (e) {
    throw new Error(`${contextMessage}: ${e.message}`);
  }
}

function extractErrorMessage(payload, fallback) {
  if (!payload) return fallback;
  if (typeof payload === 'string' && payload.trim()) return payload;
  if (typeof payload?.message === 'string' && payload.message.trim()) return payload.message;
  if (typeof payload?.error === 'string' && payload.error.trim()) return payload.error;
  return fallback;
}

async function browserRequest({ method = 'GET', url, headers = {}, body = null, expect = 'json' }) {
  const response = await fetch(url, {
    method,
    headers: withDefaultHeaders(headers),
    body,
    credentials: 'include'
  });

  const responseHeaders = Object.fromEntries(response.headers.entries());
  const contentType = responseHeaders['content-type'] || '';

  if (expect === 'blob') {
    const blob = await response.blob();

    if (!response.ok) {
      let errorText = '';
      try {
        errorText = await blob.text();
      } catch (e) {
        errorText = '';
      }
      throw new Error(errorText || `HTTP ${response.status}`);
    }

    return {
      statusCode: response.status,
      contentType,
      headers: responseHeaders,
      data: blob
    };
  }

  const text = await parseErrorResponseText(response);

  if (!response.ok) {
    throw new Error(text || `HTTP ${response.status}`);
  }

  let data = text;
  if (expect === 'json' && text) {
    data = safeJsonParse(text, `Invalid JSON from ${url}`);
  }

  return {
    statusCode: response.status,
    contentType,
    headers: responseHeaders,
    data
  };
}

function decodeBase64ToBlob(base64Data, mimeType = 'application/octet-stream') {
  const binary = atob(base64Data || '');
  const bytes = new Uint8Array(binary.length);

  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }

  return new Blob([bytes], { type: mimeType });
}

async function pluginRequest({ method = 'GET', url, headers = {}, body = null, expect = 'json', timeoutMs }) {
  if (!window?.$PAPI?.s3Request) {
    throw new Error('Plugin transport is unavailable');
  }

  const responseType = expect === 'blob' ? 'base64' : 'text';
  const payload = {
    method,
    targetUrl: url,
    headers: withDefaultHeaders(headers),
    responseType
  };

  if (body?.multipart) {
    payload.multipart = body.multipart;
  } else if (body != null) {
    payload.textBody = typeof body === 'string' ? body : JSON.stringify(body);
  }

  const result = await withTimeout(
    window.$PAPI.s3Request(payload),
    timeoutMs ?? DEFAULT_PLUGIN_TIMEOUT_MS,
    `${method} ${url}`
  );
  const statusCode = Number(result?.statusCode || 0);
  const data = result?.data ?? '';
  const contentType = result?.contentType || '';
  const responseHeaders = result?.headers || {};

  if (!statusCode) {
    throw new Error('Plugin transport returned empty status code');
  }

  if (statusCode >= 400) {
    let errorPayload = data;

    if (contentType.includes('application/json') && typeof data === 'string' && data.trim()) {
      try {
        errorPayload = JSON.parse(data);
      } catch (e) {
        errorPayload = data;
      }
    }

    throw new Error(extractErrorMessage(errorPayload, `HTTP ${statusCode}`));
  }

  if (expect === 'blob') {
    const mime = contentType || 'application/octet-stream';
    return {
      statusCode,
      contentType: mime,
      headers: responseHeaders,
      data: decodeBase64ToBlob(data, mime)
    };
  }

  let parsedData = data;
  if (expect === 'json' && data) {
    parsedData = typeof data === 'string'
      ? safeJsonParse(data, `Invalid plugin JSON from ${url}`)
      : data;
  }

  return {
    statusCode,
    contentType,
    headers: responseHeaders,
    data: parsedData
  };
}

async function request(options) {
  return isIdeaPlugin() ? pluginRequest(options) : browserRequest(options);
}

function encodeBase64(uint8Array) {
  let binary = '';
  const chunk = 0x8000;

  for (let i = 0; i < uint8Array.length; i += chunk) {
    binary += String.fromCharCode.apply(null, uint8Array.subarray(i, i + chunk));
  }

  return btoa(binary);
}

function encodeBase64Async(uint8Array) {
  return new Promise((resolve, reject) => {
    const blob = new Blob([uint8Array]);
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = String(reader.result || '');
      const commaIndex = dataUrl.indexOf(',');
      resolve(commaIndex >= 0 ? dataUrl.substring(commaIndex + 1) : '');
    };
    reader.onerror = () => reject(reader.error || new Error('FileReader error при base64-кодировании'));
    reader.readAsDataURL(blob);
  });
}

function utf8ToBase64(value) {
  const bytes = new TextEncoder().encode(String(value || ''));
  return encodeBase64(bytes);
}

function validatePluginFile(file, index) {
  if (!file) {
    throw new Error(`File at index ${index} is empty`);
  }
  if (!file.fileName || !String(file.fileName).trim()) {
    throw new Error(`File at index ${index} has empty fileName`);
  }
  if (!(file.uint8Array1 instanceof Uint8Array)) {
    throw new Error(`File "${file.fileName}" has invalid binary content`);
  }
}

function validateFiles(files) {
  if (!Array.isArray(files) || files.length === 0) {
    throw new Error('No files to upload');
  }

  files.forEach((file, index) => validatePluginFile(file, index));
}

function buildUploadMeta(description = '', pageContext = {}, originalName = '') {
  const normalizedContext = normalizePageContext(pageContext);

  return {
    description: description || '',
    pageUrl: normalizedContext.pageUrl,
    pageObjectId: normalizedContext.pageObjectId,
    pageTitle: normalizedContext.pageTitle,
    rowId: normalizedContext.rowId,
    originalName: originalName || ''
  };
}

async function toMultipartBody(files, description, fieldName, pageContext = {}) {
  const originalName = files.length === 1 ? (files[0]?.fileName || '') : '';
  const meta = buildUploadMeta(description, pageContext, originalName);

  const fileParts = await Promise.all(files.map(async(file) => ({
    fieldName,
    filename: file.fileName,
    contentType: file.mimeType || 'application/octet-stream',
    base64Data: await encodeBase64Async(file.uint8Array1)
  })));

  return {
    multipart: {
      parts: [
        {
          fieldName: 'meta',
          filename: 'meta.json',
          contentType: 'application/json; charset=UTF-8',
          base64Data: utf8ToBase64(JSON.stringify(meta))
        },
        ...fileParts
      ]
    }
  };
}

function toBrowserFile(file) {
  return new File([file.uint8Array1], file.fileName, {
    type: file.mimeType || 'application/octet-stream',
    lastModified: Date.now()
  });
}

function buildUploadFormData(files, description = '', fileFieldName = 'file', pageContext = {}) {
  const formData = new FormData();

  files.forEach(file => {
    formData.append(fileFieldName, toBrowserFile(file));
  });

  const originalName = files.length === 1 ? (files[0]?.fileName || '') : '';
  const meta = buildUploadMeta(description, pageContext, originalName);

  formData.append(
    'meta',
    new Blob(
      [JSON.stringify(meta)],
      { type: 'application/json;charset=UTF-8' }
    ),
    'meta.json'
  );

  return formData;
}

export async function uploadAsyncFiles(files, description = '', pageContext = buildCurrentPageContext()) {
  validateFiles(files);

  const normalizedPageContext = normalizePageContext(pageContext);
  const isSingle = files.length === 1;
  const url = apiUrl(isSingle ? 'upload' : 'upload/batch');
  const fileFieldName = isSingle ? 'file' : 'files';

  if (isIdeaPlugin()) {
    return (await request({
      method: 'POST',
      url,
      body: await toMultipartBody(files, description, fileFieldName, normalizedPageContext),
      expect: 'json'
    })).data;
  }

  const formData = buildUploadFormData(files, description, fileFieldName, normalizedPageContext);

  return (await request({
    method: 'POST',
    url,
    body: formData,
    expect: 'json'
  })).data;
}

export async function getFileStatus(fileId) {
  return (await request({ method: 'GET', url: apiUrl(`${fileId}/status`), expect: 'json' })).data;
}

export async function getBatchStatus(batchId) {
  return (await request({ method: 'GET', url: apiUrl(`batch/${batchId}/status`), expect: 'json' })).data;
}

export async function getMyFiles() {
  return (await request({ method: 'GET', url: apiUrl('my/files'), expect: 'json' })).data;
}

export async function recheckUpload(fileId) {
  return (await request({ method: 'POST', url: apiUrl(`${fileId}/recheck/upload`), expect: 'json'})).data;
}

export async function recheckDownload(fileId) {
  return (await request({ method: 'POST', url: apiUrl(`${fileId}/recheck/download`), expect: 'json'})).data;
}


export async function requestDownload(fileId) {
  return await request({ method: 'GET', url: apiUrl(`${fileId}/download`), expect: 'blob' });
}

export function getDownloadWaitingPageUrl(fileId) {
  return apiUrl(`${fileId}/download/page`);
}

export async function requestDownloadGate(fileId) {
  return (await request({ method: 'GET', url: apiUrl(`${fileId}/download`), expect: 'json' })).data;
}

function buildLegacyUploadLinks(fileStatuses = []) {
  const items = Array.isArray(fileStatuses) ? fileStatuses : [fileStatuses];

  return items
    .filter(item => item?.fileId)
    .map(item => {
      const downloadHref = apiUrl(`${item.fileId}/download`);
      const waitingPageHref = apiUrl(`${item.fileId}/download/page`);
      const text = item.originalName || item.fileName || item.fileId;

      return {
        href: waitingPageHref,
        downloadHref,
        waitingPageHref,
        text,
        fileId: item.fileId,
        originalName: item.originalName || item.fileName || '',
        status: item.status || '',
        uploadValidated: !!item.uploadValidated
      };
    });
}

export function buildLegacyUploadResponse(fileStatusOrStatuses) {
  const items = Array.isArray(fileStatusOrStatuses)
    ? fileStatusOrStatuses.filter(Boolean)
    : [fileStatusOrStatuses].filter(Boolean);

  const primary = items[0] || null;
  const links = buildLegacyUploadLinks(items);

  const cellValue = links.map(link => ({
    href: link.href,
    text: link.text
  }));

  const primaryLink = cellValue[0] || null;

  return {
    descriptor: {
      uploadCloudInfo: {
        serviceUrl: cellValue,
        cloudUrl: cellValue,
        rawServiceUrl: primaryLink?.href || '',
        rawCloudUrl: primaryLink?.href || '',
        fileUUID: primary?.fileId || '',
        originalName: primary?.originalName || primary?.fileName || '',
        items: cellValue,
        links: cellValue,
        cellText: cellValue,
        plainText: links.map(link => `${link.text}: ${link.href}`).join('\n')
      }
    },
    asyncFile: primary,
    asyncFiles: items
  };
}

