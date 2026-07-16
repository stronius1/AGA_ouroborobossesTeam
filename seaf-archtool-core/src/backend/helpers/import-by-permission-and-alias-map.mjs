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
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber

  Contributors:
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2026
*/

/**
 * В рут манифесте для кластера мы храним объекты с описанием импортов, каждый импорт может содержать несколько атрибутов
 * На 04.2026 обязательный root, permission и alias
 * В некоторых сценариях нам нужно получить объект импорта по permission в других по alias
 * Этот класс дает апи для доступа к ним за О1 за счет использования Map
 * Уникальность permission и alias в пределах одного рут файла обеспечивается при загрузке manifest-loader
 */
export class ImportByPermissionAndAliasMap {
    /** @type {Map} */
    _byPermission;
    /** @type {Map} */
    _byAlias;

    constructor(imports) {
        if (imports && Array.isArray(imports)) {
            this._byPermission = new Map(imports.map(item => [item.permission, item]));
            this._byAlias = new Map(imports.map(item => [item.alias, item]));
        } else {
            this._byPermission = new Map();
            this._byAlias = new Map();
        }
    }

    // Статический метод для создания пустого экземпляра
    static createEmpty() {
        return new ImportByPermissionAndAliasMap(null);
    }

    getByPermission(permission) {
        return this._byPermission.get(permission);
    }
    getByAlias(alias) {
        return this._byAlias.get(alias);
    }

    /**
     * @returns {number}
     */
    size() {
        return this._byPermission.size;
    }
}
