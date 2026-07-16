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
      Navasardyan Suren, Sber - 2022
      Navasardyan Suren, Sber - 2023
*/

module.exports = {
    preset: 'ts-jest',
    testEnvironment: 'node',
    testResultsProcessor: 'jest-sonar-reporter',
    collectCoverageFrom: [
        'src/global/helpers/username-policy.ts',
        '!**/*.test.ts'
    ],
    coveragePathIgnorePatterns: [
        '/node_modules/',
        '/dist/',
        '/build/',
        '/out/',
        '/coverage/',
        '/src/generated/'
    ],
    testPathIgnorePatterns: [
        '/node_modules/',
        '/dist/',
        '/build/',
        '/out/',
        '/tests/global/parser/documentation-parser.test.js',
        '/tests/global/datasets/dataset.test.js',
        '/tests/indexedDB/cache.spec.ts',
        '/tests/global/parser/single-parser.test.js',
        '/plugins/dbml/'
    ],
    setupFiles: [
        'fake-indexeddb/auto',
        'dotenv/config'
    ],
    setupFilesAfterEnv: [
        '<rootDir>/jest.setup.cjs'
    ],
    transform: {
        '^.+\\.js$': ['babel-jest', {configFile: './babel-jest.config.cjs'}],
        '^.+\\.mjs$': ['babel-jest', {configFile: './babel-jest.config.cjs'}],
        '^.+\\.ts$': 'babel-jest'
    },
    transformIgnorePatterns: [
        '<rootDir>/node_modules/'
    ],
    moduleDirectories: [
        'node_modules',
        'src'
    ],
    moduleNameMapper: {
        uuid: require.resolve('uuid'),
        '^@front/(.*)': '<rootDir>/src/frontend/$1',
        '^@global/(.*)': '<rootDir>/src/global/$1',
        '^@back/(.*)': '<rootDir>/src/backend/$1'
    },
    moduleFileExtensions: [
        'js',
        'ts',
        'tsx',
        'vue'
    ],
    verbose: true
};
