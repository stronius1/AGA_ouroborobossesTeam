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
export const ALLOWED_UPLOAD_FILE_TYPES = Object.freeze([
  '.doc', '.docx',
  '.xls', '.txt',
  '.json', '.csv', '.png',
  '.jpeg', '.jpg','.yaml', '.yml', '.xml',
  '.pdf'
]);


export function normalizeFileTypes(fileTypes) {
  return (fileTypes || [])
    .map(x => String(x || '').trim().toLowerCase())
    .filter(Boolean)
    .map(x => (x.startsWith('.') ? x : `.${x}`));
}
