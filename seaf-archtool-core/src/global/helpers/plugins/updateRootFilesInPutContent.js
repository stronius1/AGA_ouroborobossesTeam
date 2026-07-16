/*
  Copyright (C) 2025 Sber

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

import parser, { SourceItem } from '@global/manifest/parser3/index.mjs';
import yaml from 'yaml';

function createUriByPath(path, baseUri, rootUri) {
  const rootUriPathListLength = rootUri.split('/').length;
  const uriPathList = baseUri.split('/');
  const pathList = path.split('/').filter(Boolean);

  return pathList
    .slice(0, -1)
    .reduce((acc, dir) => {
      if (dir === '.') {
        return acc;
      } else if (dir === '..') {
        if (acc.length > rootUriPathListLength) {
          acc.splice(acc.length - 2, 1);
        }
        return acc;
      } else {
        acc.splice(acc.length - 1, 0, dir);
        return acc;
      }
    }, uriPathList.slice(0, -1).concat(pathList.at(-1)))
    .join('/');
}

function createRelativePath(baseUri, targetUri) {
  const baseUriPathList = baseUri.split('/').slice(0, -1);
  const targetUriPathList = targetUri.split('/').slice(0, -1);

  const resultPathList = [];
  const maxLength = Math.max(baseUriPathList.length, targetUriPathList.length);
  for (let i = 0; i < maxLength; i++) {
    if (baseUriPathList[i] !== targetUriPathList[i]) {
      resultPathList.push(
        ...baseUriPathList.slice(i).fill('..'),
        ...targetUriPathList.slice(i)
      );
      break;
    }
  }

  resultPathList.push(targetUri.split('/').at(-1));
  return resultPathList.join('/');
}

function updateImportsInSource(source, uri) {
  const manifest =
    source instanceof SourceItem ? { ...source?.manifest } : { ...source };

  manifest.imports = source.imports
    ? source.imports.includes(uri)
      ? [...source.imports]
      : [...source.imports, uri]
    : [uri];
  return manifest;
}

export default function updateRootFilesInPutContent({
  rootUri,
  baseUri,
  indexFileName,
  commitData,
  manifestParser = parser
}) {
  const filesURIList = Object.keys(commitData).map((path) =>
    createUriByPath(path, baseUri, rootUri)
  );

  const notConnectedFilesURIList = filesURIList.filter(
    (uri) => !manifestParser.sources[uri]
  );

  const rootUriPathListLength = rootUri.split('/').length;
  const indexFilesURIToConnect = notConnectedFilesURIList.map((uri) => {
    const path = createUriByPath(indexFileName, uri, rootUri);
    return rootUriPathListLength === path.split('/').length ? rootUri : path;
  });

  const updatedDataFromIndexFilesToConnect = indexFilesURIToConnect.reduce(
    (acc, uri, index) => {
      const source = acc[uri] || manifestParser.sources[uri] || {};
      const pathToImport = notConnectedFilesURIList[index];
      const updatedSource = updateImportsInSource(source, pathToImport);
      return Object.assign(acc, { [uri]: updatedSource });
    },
    {}
  );

  const notConnectedIndexFilesURIList = Object.keys(
    updatedDataFromIndexFilesToConnect
  ).filter((uri) => !manifestParser.sources[uri]);

  const generateImports = (content, importURI) => {
    const slicedUri = importURI.split('/');
    const isRootDirectory = slicedUri.length === rootUri.split('/').length;

    const nextLevelUri = isRootDirectory
      ? rootUri
      : slicedUri.slice(0, -2).concat(indexFileName).join('/');

    const isNextLevelUriImported = Boolean(
      content[nextLevelUri] || parser.sources[nextLevelUri]
    );

    const source = content[nextLevelUri] || parser.sources[nextLevelUri] || {};
    content[nextLevelUri] = updateImportsInSource(source, importURI);

    return isNextLevelUriImported || isRootDirectory
      ? content
      : generateImports(content, nextLevelUri);
  };

  const importsToUpdate = notConnectedIndexFilesURIList.reduce(
    generateImports,
    updatedDataFromIndexFilesToConnect
  );

  const result = Object.keys(importsToUpdate).reduce((acc, connectUri) => {
    const data = { ...importsToUpdate[connectUri] };
    data.imports = data.imports.map((uri) =>
      createRelativePath(connectUri, uri)
    );

    connectUri =
      rootUri === connectUri
        ? createUriByPath('dochub.yaml', connectUri, rootUri)
        : connectUri;
    const relativeConnectPath = createRelativePath(baseUri, connectUri);

    const yamledData = yaml.stringify(data);

    return Object.assign(acc, { [relativeConnectPath]: yamledData });
  }, {});

  return result;
}
