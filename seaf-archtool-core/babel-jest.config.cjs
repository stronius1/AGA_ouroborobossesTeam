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
      Navasardyan Suren, Sber

  Contributors:
      Navasardyan Suren, Sber - 2023
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2024
*/

module.exports = {
  presets: [
    ['@babel/preset-typescript', { 'onlyRemoveTypeImports': true }],
    '@vue/cli-plugin-babel/preset',
    '@babel/preset-env'
  ],
  plugins: [
    '@babel/plugin-proposal-class-properties',
    '@babel/proposal-object-rest-spread',
    '@babel/transform-runtime',
    'babel-plugin-transform-import-meta',
    ['prismjs', {
      'languages': 'all',
      'theme': 'default',
      'css': true
    }]
  ]
};
