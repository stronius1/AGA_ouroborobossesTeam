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
      R.Piontik <r.piontik@mail.ru> - 2023
*/

const COMPRESS_METHOD = 'gzip'; //deflate

export default function(driver) {

    const compressor = {
        // eslint-disable-next-line no-undef
        DecompressionStream: driver?.DecompressionStream || DecompressionStream,
        // eslint-disable-next-line no-undef
        CompressionStream: driver?.CompressionStream || CompressionStream
    };

    return {
        // Упаковывает строку в COMPRESS_METHOD
        encodeBin: async function(str) {
            const byteArray = new TextEncoder().encode(str);
            const cs = new compressor.CompressionStream(COMPRESS_METHOD);
            const writer = cs.writable.getWriter();
            writer.write(byteArray);
            writer.close();
            return new Response(cs.readable).arrayBuffer();
        },

        // Упаковывает строку в COMPRESS_METHOD и кодирует в base64
        encodeBase64: async function(str) {
            const bin = new Uint8Array(await this.encodeBin(str));
            const strOut = String.fromCodePoint(...bin);
            const base64 = btoa(strOut);
            return base64;
        },

        // Распаковывает byteArray из COMPRESS_METHOD в строку
        decodeBin: async function(byteArray) {
            const cs = new compressor.DecompressionStream(COMPRESS_METHOD);
            const writer = cs.writable.getWriter();
            writer.write(byteArray);
            writer.close();
            return new TextDecoder().decode(await new Response(cs.readable).arrayBuffer());
        },

        // Распаковывает строку из COMPRESS_METHOD и кодирует в base64
        decodeBase64: async function(base64) {
            const str = atob(base64);
            const bin = Uint8Array.from(Buffer.from(str, 'binary'));
            const result = await this.decodeBin(bin);
            return result;
        }
    };
}

