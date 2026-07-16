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


import { strToU8, deflateSync } from 'fflate';

/**
 * Envelope arbitrary JSON or text into SEAF document.
 *
 * @param {unknown} input
 *   - JS value
 *   - JSON string
 *   - plain text
 *
 * @returns Envoloped data
 */
export function envelopeDocument(input) {
    if (input === undefined) {
        input = null;
    }

    const detected = detectInputKind(input);

    if (detected.kind === 'json') {
        return {
            docType: 'application/json',
            schemaVersion: '1',
            root: encodeValue(detected.value)
        };
    }

    return {
        docType: 'text/plain',
        schemaVersion: '1',
        root: encodeStringValue(detected.value)
    };
}

function detectInputKind(input) {
    if (typeof input !== 'string') {
        return {
            kind: 'json',
            value: input
        };
    }

    const s = input.trim();

    if (s.length === 0) {
        return { kind: 'text', value: input };
    }

    const first = s[0];
    const last = s[s.length - 1];

    if ((first === '{' && last === '}') || (first === '[' && last === ']')) {
        try {
            const parsed = JSON.parse(s);
            return { kind: 'json', value: parsed };
        } catch {
            return { kind: 'text', value: input };
        }
    }

    return { kind: 'text', value: input };
}

function encodeValue(value) {
    if (value === null) {
        return {
            t: 'null',
            v: null
        };
    }

    if (typeof value === 'boolean') {
        return {
            t: 'bool',
            v: value
        };
    }

    if (typeof value === 'string') {
        return encodeStringValue(value);
    }

    if (typeof value === 'number') {
        return encodeNumberValue(value);
    }

    if (Array.isArray(value)) {
        return encodeArrayValue(value);
    }

    if (typeof value === 'object') {
        return encodeObjectValue(value);
    }

    throw new Error('Unsupported value type');
}

function encodeStringValue(value) {
    if (value.length <= 255) {
        return {
            t: 'str',
            v: value
        };
    }

    const compressed = compressString(value);

    if (compressed.length <= 255) {
        return {
            t: 'str',
            v: compressed,
            compressed: true
        };
    }

    return {
        t: 'txt',
        v: chunkString(compressed, 255),
        compressed: true
    };
}

function encodeNumberValue(value) {
    if (!Number.isFinite(value)) {
        throw new Error('Non-finite numbers are not supported');
    }

    if (Number.isInteger(value) && value >= -2147483648 && value <= 2147483647) {
        return {
            t: 'i32',
            v: value
        };
    }

    return {
        t: 'dec',
        v: value.toString()
    };
}

function encodeArrayValue(value) {
    const entries = {};
    let index = 0;

    for (const item of value) {
        entries[String(index)] = encodeValue(item);
        index += 1;
    }

    return {
        t: 'arr',
        v: entries
    };
}

function encodeObjectValue(value) {
    const entries = {};
    let index = 0;

    for (const [key, val] of Object.entries(value)) {
        entries[String(index)] = {
            k: key,
            v: encodeValue(val)
        };
        index += 1;
    }

    return {
        t: 'obj',
        v: entries
    };
}

function compressString(value) {
    const bytes = strToU8(value);
    const compressed = deflateSync(bytes);

    let binary = '';
    const len = compressed.length;

    for (let i = 0; i < len; i++) {
        binary += String.fromCharCode(compressed[i]);
    }

    return btoa(binary);
}

function chunkString(value, maxChunkLength) {
    const chunks = {};
    let index = 0;

    for (let i = 0; i < value.length; i += maxChunkLength) {
        chunks[String(index)] = value.slice(i, i + maxChunkLength);
        index += 1;
    }

    return chunks;
}

