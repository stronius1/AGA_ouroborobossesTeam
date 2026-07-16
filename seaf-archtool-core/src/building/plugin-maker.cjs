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
      R.Piontik <r.piontik@mail.ru> - 2022
*/

const pluginName = 'PluginMakerWebpackPlugin';

const { ConcatSource } = require('webpack-sources');

module.exports = class PluginMakerWebpackPlugin {
	constructor(options) {
		this.options = Object.assign(options || {}, {
			filer: /^plugins\/.*\.js$/
		});
		this.options.test = new RegExp(this.options.test);
	}
	apply(compiler) {
		compiler.hooks.compilation.tap(pluginName, compilation => {
			compilation.hooks.processAssets.tap(
				{
					name: pluginName,
					stage: compilation.PROCESS_ASSETS_STAGE_ADDITIONS
				},
				() => {
					for (const chunk of compilation.chunks) {
						for (const file of chunk.files) {
							if (this.options.filer.test(file)) {
								compilation.updateAsset(file, old => {
									return new ConcatSource('(function (DocHub){', old, '})(window.DocHub);');
								});
							}
						}
					}
				});
		});
	}
};
