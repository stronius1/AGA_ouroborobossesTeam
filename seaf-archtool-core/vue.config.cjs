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
      Navasardyan Suren, Sber - 2023
      R.Piontik <r.piontik@mail.ru> - 2023
      Vladislav Markin <markinvy@yandex.ru>, Sber - 2025
      Bejoy <casperyourweb@gmail.com> - 2023
*/

const WebpackPwaManifest = require('webpack-pwa-manifest');
const HtmlWebpackPlugin = require('html-webpack-plugin');
const HtmlWebpackInlineSourcePlugin = require('@effortlessmotion/html-webpack-inline-source-plugin');
const MonacoWebpackPlugin = require('monaco-editor-webpack-plugin');
// const BundleAnalyzerPlugin = require('webpack-bundle-analyzer').BundleAnalyzerPlugin;
const pluginsConf = require('./plugins.json');
const PluginMaker = require('./src/building/plugin-maker.cjs');
const path = require('path');
const packageJson = require('./package.json');
const webpack = require('webpack');

const plugins = [
    new webpack.DefinePlugin({
        __APP_VERSION__: JSON.stringify(packageJson.version)
    })
];
const entries = {
    app: './src/frontend/main.js'
};

// Указывается где лежит движок SmartAnts
!process.env.VUE_APP_DOCHUB_SMART_ANTS_SOURCE && (process.env.VUE_APP_DOCHUB_SMART_ANTS_SOURCE = '@assets/libs/smartants.cjs');


// Определяем версии API плагинов, которые поддерживаются в Enterprise режиме
const ideaAPIAvailable = process.env.VUE_APP_DOCHUB_IDE_IDEA_API || packageJson.ide?.idea?.api || [];
process.env.VUE_APP_DOCHUB_IDE_IDEA_API = Array.isArray(ideaAPIAvailable) ? ideaAPIAvailable : ideaAPIAvailable.toString().split(',');

const vscodeAPIAvailable = process.env.VUE_APP_DOCHUB_IDE_VSCODE_API || packageJson.ide?.vscode?.api || [];
process.env.VUE_APP_DOCHUB_IDE_IDEA_API = Array.isArray(vscodeAPIAvailable) ? vscodeAPIAvailable : vscodeAPIAvailable.toString().split(',');

// Собираем встраиваемые плагины
//if (process.env.VUE_APP_DOCHUB_MODE === 'production') {
(pluginsConf?.inbuilt || []).map((item) => {
    const config = require(`./${item}/package.json`);
    entries[`plugins/${item}`] = `./${item}/${config.main || 'index.js'}`;
});
//}

// Добавляем в манифест внешние плагины
const manifest = {
    name: 'SEAF.ArchTool',
    short_name: 'SEAF.ArchTool',
    description: 'Architecture as a code',
    background_color: '#ffffff',
    crossorigin: 'use-credentials',
    plugins: pluginsConf?.external,
    filename: 'manifest.json'
};

plugins.push(new WebpackPwaManifest(manifest));

// Добавляем собственный плагин-мейкер
plugins.push(new PluginMaker());

plugins.push(new MonacoWebpackPlugin());

if (process.env.VUE_APP_DOCHUB_MODE === 'plugin') {
    plugins.push(new HtmlWebpackPlugin({
        filename: 'plugin.html',
        template: 'src/ide/plugin.html',
        inlineSource: '.(woff(2)?|ttf|eot|svg|js|css)$',
        inject: true
        /* ,
        minify: {
            removeComments: true,
            collapseWhitespace: true,
            removeAttributeQuotes: true,
            minifyCSS: true,
            minifyJS: true
            // more options:
            // https://github.com/kangax/html-minifier#options-quick-reference
        } */
    }));
    plugins.push(new HtmlWebpackInlineSourcePlugin());
} else {
    // plugins.push(new BundleAnalyzerPlugin());
}

// Дефолтная конфигурация dev-сервера
let config = {
    publicPath: '/',
    runtimeCompiler: true,
    devServer: {
        port: 9090,
        headers: {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, PATCH, OPTIONS',
            'Access-Control-Allow-Headers': 'X-Requested-With, content-type, Authorization'
        },
        historyApiFallback: true,
        /*
        allowedHosts: [
            'localhost'
        ],
        */
        client: {
			overlay: false,
			logging: 'info'
		},
        hot: process.env.VUE_APP_DOCHUB_HOTRELOAD !== 'off',
        proxy: {
            '/oauth': {
                target: 'https://sm-auth-sd.prom-88-89-apps.ocp-geo.ocp.sigma.sbrf.ru/api/v2',
                // target: "https://ngw.devices.sberbank.ru:9443/api/v2",
                secure: false
            },
            '/chat/completions': {
                target: 'https://gigachat.devices.sberbank.ru/api/v1',
                secure: false
            },
            ...(process.env.VUE_APP_PROXY_BACKEND_URL && {
                '^/api|^/core|^/entities/\\S+/presentations|^/new/chat|^/logger|^/manifest-mutation|^/health|^/smartants|^/bitbucket-mgr': {
                    target: process.env.VUE_APP_PROXY_BACKEND_URL,
                    secure: false,
                    logLevel: 'debug',
                    onProxyReq: (proxyReq, req, res) => {
                        proxyReq.setHeader('Authorization', 'Bearer ' + process.env.VUE_APP_DEBUG_IAM_TOKEN);
                    }
                }
            })
        }
    },
    transpileDependencies: ['vueitfy'],
    configureWebpack: {
        cache: (process.env.VUE_APP_DOCHUB_BUILDING_CACHE || 'memory').toLowerCase() === 'filesystem'
            ? {
                type: 'filesystem',
                compression: 'gzip',
                allowCollectingMemory: true
            }
            : {
                type: 'memory'
            },
        optimization: {
            splitChunks: false,
            runtimeChunk: 'single'
        },
        entry: {...entries},
        plugins,
        module: {
            rules: [
                {
                    test: /\.mjs$/,
                    include: /node_modules/,
                    type: 'javascript/auto'
                },
                {
                    test: /\.([cm]?ts|tsx)$/,
                    use: [
                        {
                            loader: 'ts-loader',
                            options: {
                                transpileOnly: true,
                                compilerOptions: {
                                    noEmit: false
                                }
                            }
                        }
                    ],
                    exclude: /node_modules/
                }
            ]
        },
        output: {
            filename: '[name].js'
        },
        resolve: {
            alias: {
                '@front': path.resolve(__dirname, './src/frontend'),
                '@assets': path.resolve(__dirname, './src/assets'),
                '@back': path.resolve(__dirname, './src/backend'),
                '@idea': path.resolve(__dirname, './src/ide/idea'),
                '@vscode': path.resolve(__dirname, './src/ide/vscode'),
                '@ide': path.resolve(__dirname, './src/ide'),
                '@global': path.resolve(__dirname, './src/global'),
                '@': path.resolve(__dirname, './'),
                vue: path.resolve(__dirname, './node_modules/vue')
            },
            extensions: ['.ts', '.js', '.tsx', '.jsx']
        }
    }
};

// Подключает сертификаты, если они обнаружены
/*
if(fs.lstatSync(__dirname + '/certs').isDirectory()) {
	config.devServer = {
		http2: true,
		https: {
			key: fs.readFileSync(__dirname + '/certs/server.key'),
			cert: fs.readFileSync(__dirname + '/certs/server.cert')
		}
	}
}
*/
module.exports = config;
