/*
  Copyright (C) 2023 Sber

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
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber

  Contributors:
      Alexandr Anenburg <anenburg.alexandr@mail.ru>, Sber - 2025
*/

const manifestPropsValidators = {
  imports(manifest) {
    if (manifest?.imports && !Array.isArray(manifest.imports)) {
      const msg = `\nОшибка при описании "imports":\nДопустимый формат: [array].\nУказаный формат: [${typeof manifest.imports}].\n`;
      throw new SyntaxError(msg);
    }
  }
};

export const validateManifestData = (manifest) => {
  for (let key in manifestPropsValidators) {
    const validator = manifestPropsValidators[key];
    validator(manifest);
  }
};
