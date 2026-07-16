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
      Vladislav Markin, Sber

  Contributors:
      Vladislav Markin, Sber - 2026
*/

import { strFromU8, inflateSync } from 'fflate';

export function unenvelopeDocument(document) {
    if (document.docType === 'application/json') {
        return decodeValue(document.root);
    }

    if (document.docType === 'text/plain') {
        return decodeValue(document.root);
    }

    throw new Error(`Unsupported docType: ${document.docType}`);
}

function decodeValue(value) {
    switch (value.t) {
        case 'null':
            return null;

        case 'bool':
            return value.v;

        case 'str':
            return decodeStringValue(value);

        case 'txt':
            return decodeStringValue(value);

        case 'i32':
            return value.v;

        case 'dec':
            return Number(value.v);

        case 'arr':
            return decodeArrayValue(value);

        case 'obj':
            return decodeObjectValue(value);

        default:
            throw new Error(`Unsupported value type: ${value.t}`);
    }
}

function decodeStringValue(value) {
    let str;

    if (value.t === 'str') {
        str = value.v;
    } else if (value.t === 'txt') {
        str = decodeTxtChunks(value.v);
    } else {
        throw new Error(`Invalid string container: ${value.t}`);
    }

    if (value.compressed) {
        return decompressString(str);
    }

    return str;
}

// Без сортировки. С допущением, что последовательность сохранена
function decodeArrayValue(value) {
    const result = [];

    for (const entry of Object.values(value.v)) {
        result.push(decodeValue(entry));
    }

    return result;
}

// Без сортировки. С допущением, что последовательность сохранена
function decodeObjectValue(value) {
    const result = {};

    for (const entry of Object.values(value.v)) {
        result[entry.k] = decodeValue(entry.v);
    }

    return result;
}

// Без сортировки. С допущением, что последовательность сохранена
function decodeTxtChunks(chunks) {
    let result = '';

    for (const chunk of Object.values(chunks)) {
        result += chunk;
    }

    return result;
}

function decompressString(value) {
    const binary = atob(value);
    const len = binary.length;
    const bytes = new Uint8Array(len);

    for (let i = 0; i < len; i++) {
        bytes[i] = binary.charCodeAt(i);
    }

    const decompressed = inflateSync(bytes);
    return strFromU8(decompressed);
}
