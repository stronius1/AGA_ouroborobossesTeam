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
      Sergeev Viktor <sergeevviktor017@gmail.com>, Sber - 2025
      Alexander Romashin <romashin.a.va@sberbank.ru>, Sber - 2025
*/

import {makeURIByBaseURI} from '../tools/uri.mjs';

import {
  checkIsObject,
  createChildPath,
  createRepositoryIDfromURI,
  getImportsDifferences,
  getStorePath
} from './helpers.mjs';
import {extractFrontmatter} from '@global/manifest/tools/yamlHeader.mjs';
import { validateManifestData } from './manifestValidator.mjs';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

const LOG_TAG = 'parser3.index.mjs';
const logger = getLoggerWithTag(LOG_TAG);

class PackageError extends Error {
  constructor(uri, message) {
    super(message);
    this.name = 'Package';
    this.uri = uri;
  }
}

class SyntaxError extends Error {
  constructor(uri, message) {
    super(message);
    this.name = 'syntax';
    this.uri = uri;
  }
}

export class SourceItem {
  constructor({ ownerUri, uri, data }) {
    this.uri = uri;
    this.ownerUri = ownerUri;
    this.manifest = data;

    const imports = data?.imports ?? [];
    this.imports = imports.map((path) => makeURIByBaseURI(path, uri));

    delete this.manifest.imports;
  }
}

class RepositorySource {
  constructor() {
    this.repositorySources = new Set();
  }

  _checkIsRepositoryURI(uri) {
    return uri.startsWith('bitbucket:') || uri.startsWith('gitlab:');
  }

  _createRepositoryIDfromURI(uri) {
    return createRepositoryIDfromURI(uri);
  }

  addRepositorySource(uri) {
    if(this._checkIsRepositoryURI(uri)) {
      const repositoryID = this._createRepositoryIDfromURI(uri);
      this.repositorySources.add(repositoryID);
    }
  }

  removeRepositorySource(uri) {
    if(this._checkIsRepositoryURI(uri)) {
      const repositoryID = this._createRepositoryIDfromURI(uri);
      this.repositorySources.delete(repositoryID);
    }
  }
}

export class Parser extends RepositorySource {
  constructor(options = {}) {
    super();

    const {
      strictMode = false
    } = options;
    
    this.strictMode = strictMode;
    this.parserVersion = 'v3';

    this.rootImports = [];
    this.imports = [];
    this.sources = {};
    this.metamodels = {};

    this.sourceMap = {};
    this.mergeMap = {};

    this.manifest = {};
    this.changes = new Set();
    this.errors = {};

    this.isManifestBuilded = false;
    // признак того, что манифест в процесс загрузки
    this.manifestLoadInProgress = true;
    this.afterLoadedCallbacks = [];
  }
  static fromExistData(manifest, anotherParser) {
    if (anotherParser.parserVersion !== 'v3') {
      throw `unsupported parser version, need v3 but exist ${anotherParser.parserVersion}`;
    }
    let parser = new Parser();
    parser.strictMode = anotherParser.strictMode;
    parser.parserVersion = 'v3';

    parser.rootImports = anotherParser.rootImports;
    parser.imports = anotherParser.imports;
    parser.sources = anotherParser.sources;
    parser.metamodels = anotherParser.metamodels;

    parser.sourceMap = anotherParser.sourceMap;
    parser.mergeMap = anotherParser.mergeMap;

    parser.manifest = manifest;
    parser.changes = new Set();
    parser.errors = anotherParser.errors;

    parser.isManifestBuilded = anotherParser.isManifestBuilded;
    // признак того, что манифест в процесс загрузки
    parser.manifestLoadInProgress = anotherParser.manifestLoadInProgress;
    parser.afterLoadedCallbacks = [];
    return parser;
  }

  // ***************************** ОБРАБОТКА ОШИБОК *****************************
  // ****************************************************************************

  registerError(e, uri) {
    const errorURI = uri || e.uri;
    if(!this.errors[errorURI]) this.errors[errorURI] = {
      code: e.code,
      message: e.message,
      name: e.name
    };

    const errorPath = `$errors/requests/${new Date().getTime()}`;

    this.pushToMergeMap({ path: errorPath, location: uri });

    try {
      if (typeof e === 'string') e = JSON.parse(e);
    } catch (e) {
      true;
    }

    let errorType = (() => {
      switch (e.name) {
        case 'SyntaxError':
        case 'YAMLSyntaxError':
        case 'YAMLSemanticError':
          return 'syntax';
        case 'TypeError':
          return 'core';
        case 'EntryIsADirectory (FileSystemError)':
          return 'file-system';
        case 'Package':
          uri = e.uri;
          return 'package';
        default:
          return 'net';
      }
    })();

    this.onError &&
      this.onError(errorType, {
        uri,
        error: e
      });
  }

  refreshErrors = () => {
    for(let uri in this.errors) {
      this.registerError(this.errors[uri], uri);
    }
  }

  // ********************************* ЗАГРУЗКА *********************************
  // ****************************************************************************

  pushRequest = async(uri, baseURI) => {
    const sourceUri = makeURIByBaseURI(uri, baseURI);
    this.errors[sourceUri] && delete this.errors[sourceUri];

    const request = this.onPullSource
      ? this.onPullSource(uri,  baseURI ?? '/', this)
      : this.cache.request(uri, '/');

    return new Promise((res, rej) => {
      request
        .then((response) => {
          let data;
          if (uri?.toLowerCase()?.endsWith('.md')) {
            let markdownData = extractFrontmatter(response.data);
            data = markdownData.header ? markdownData.header : {};
          } else {
            data = typeof response.data === 'object'
                    ? response.data
                    : JSON.parse(response.data);
          }

          if (data) {
            validateManifestData(data);
            res(data);
          } else {
            throw new SyntaxError(sourceUri, 'Файл пустой или содержит ошибку в манифесте');
          }
        })
        .catch((err) => {

          if(this.strictMode) {
            // todo: систематизировать ошибки в парсере [ERA-1330]
            const error = err instanceof SyntaxError || err instanceof PackageError || err.response
              ? err 
              : new SyntaxError(sourceUri, 'Файл пустой или содержит ошибку в манифесте');
            rej(error);
          }

          this.isManifestBuilded
            ? this.errors[sourceUri] = err
            : this.registerError(err, sourceUri);
          res({});
        });
    });
  };

  _loadSourceTree({ uri, baseURI, ownerUri = null, root, sources, imports }) {
    this.pushRequest(uri, baseURI)
      .then((data) => {
        imports.push(uri);

        this.addRepositorySource(uri);

        const source = new SourceItem({
          ownerUri,
          uri: baseURI ? makeURIByBaseURI(uri, baseURI): uri,
          data
        });

        source.imports = source.imports.filter((importUri) => {
          const isDoubleImport = Boolean(sources[importUri]);
          if(isDoubleImport) {
            this.registerError(
              new PackageError(
                uri,
                `Дублирование импорта манифеста:\n${importUri}\nимпортирован в\n${sources[importUri].ownerUri}`
              )
            );
          }
          return !isDoubleImport;
        });

        sources[uri] = source;

        root.importStack += source.imports.length;

        source.imports.forEach((childUri) => {
          this._loadSourceTree({
            uri: makeURIByBaseURI(childUri, source.uri),
            ownerUri: source.uri,
            root,
            sources,
            imports
          });
        });
      })
      .catch((err) => {
        this.registerError(
            err,
            uri
        );
      })
      .finally(() => {
        root.isRootImport = false;

        root.importStack -= 1;

        if (root.importStack <= 0) {
          // Загрузка дерева импортов упешно завершена
          root.res({ sources, imports });
        }
      });
  }

  loadSourceTree({ uri, baseURI, ownerUri = null }) {
    const sources = {};
    const imports = [];

    return new Promise((res, rej) => {
      const root = { importStack: 1, res, rej, isRootImport: true };
      this._loadSourceTree({ uri, baseURI, ownerUri, root, sources, imports });
    });
  }

  import = async(uri, baseURI) => {
    try {
      const { sources, imports } = await this.loadSourceTree({ uri, baseURI });
      let startIndex = this.imports.indexOf(uri) + this.imports.length + 1;
      this.imports.splice(startIndex, 0, ...imports);
      Object.assign(this.sources, sources);
      Object.assign(this.metamodels, this._getMetamodelVersions());
      this.rootImports.push(uri);
    } catch (e) {
      if(this.strictMode) throw e;
      this.registerError(e, e?.uri || uri);
    }
  };

  _getMetamodelVersions() {
    return Object.values(this.sources)
        .filter( el => { return el.manifest.$package; })
        .map(el => {
          const pkg = el.manifest.$package;
          const key = Object.keys(pkg)[0];
          return { [key]: pkg[key].version };
        })
        .reduce((acc, curr) => ({ ...acc, ...curr }), {});
  }

  // ****************************** ОБХОД ДЕРЕВА ********************************
  // ****************************************************************************

  forEachTree = ({ uri, manifest = null, callbacks }) => {
    const source = this.sources[uri];

    if (!source) return;

    if (callbacks?.eachTree) {
      callbacks.eachTree({ source, manifest, sourceUri: uri });
    }

    this.forEachTreeItem({
      source: source.manifest,
      manifest,
      path: '/',
      structuredPath: [],
      sourceUri: uri,
      callbacks,
      parents: null
    });

    source.imports.forEach((childUri) =>
      this.forEachTree({ uri: childUri, manifest, callbacks })
    );

    if (callbacks?.afterEachTree) {
      callbacks.afterEachTree({ uri });
    }
  };

  forEachTreeItem = ({
    source,
    manifest = null,
    path,
    structuredPath,
    sourceUri,
    callbacks,
    parents
  }) => {
    if (callbacks?.eachObject) {
      callbacks.eachObject({
        source,
        manifest,
        path,
        structuredPath,
        sourceUri,
        parents
      });
    }

    const params = { source, manifest, path, sourceUri, callbacks, parents };

    for (let key in source) {
      const childPath = createChildPath(path, key);
      params.parents = { source, manifest, key, path };
      params.path = childPath;
      params.source = source[key];
      params.manifest = manifest === null ? manifest : manifest[key];
      params.structuredPath = [...structuredPath, key];

      if (checkIsObject(source[key])) {
        if (callbacks?.beforeEachObject) {
          callbacks.beforeEachObject(params);
        }

        this.forEachTreeItem(params);
      } else {
        if (callbacks?.eachProp) {
          callbacks.eachProp(params);
        }
      }
    }
  };

  // ********************************** МЕРЖ ************************************
  // ****************************************************************************

  merge = ({ source, manifest, key }) => {
    if (Array.isArray(source[key])) {
      if (!manifest[key] || !Array.isArray(manifest[key])) {
        manifest[key] = [];
      }
      this.mergeArray({ source, manifest, key });
    } else {
      manifest[key] = source[key];
    }
  };

  mergeArray = ({ source, manifest, key }) => {
    if (!manifest[key] || !Array.isArray(manifest[key])) manifest[key] = [];

    const sourceValue = source[key];
    const temp = [];
    let result = [];

    manifest[key].map((distItem) => {
      const distContent = JSON.stringify(distItem);
      if (
        !sourceValue.find((srcItem, index) => {
          !temp[index] && (temp[index] = JSON.stringify(srcItem));
          return distContent === temp[index];
        })
      ) {
        result.push(distItem);
      }
    });
    result = sourceValue.concat(result);

    manifest[key] = result;
  };

  // *********************************** MAPS ***********************************
  // ****************************************************************************

  pushToMergeMap = ({ path, sourceUri }) => {
    const storePath = getStorePath(path);

    let locations = this.mergeMap[storePath];

    !locations && (this.mergeMap[storePath] = locations = []);
    locations.indexOf(sourceUri) < 0 && locations.push(sourceUri);
  };

  createSourceMap = (path, structuredPath) => {
    this.sourceMap[path] = {
      sources: [],
      path,
      structuredPath,
      value: this.isManifestBuilded ? null : {}
    };
  };

  pushObjectToSourceMap = (path, sourceUri, parents) => {
    const { sources } = this.sourceMap[path];

    sources.push(sourceUri);

    if(!this.manifestLoadInProgress) {
      sources.sort((a, b) => {
        const indexA = this.imports.indexOf(a);
        const indexB = this.imports.indexOf(b);
        return indexA - indexB;
      });
    }

    if (
      !this.isManifestBuilded &&
      parents &&
      this.sourceMap[parents.path].value && 
      parents.key in this.sourceMap[parents.path].value
    ) {
      delete this.sourceMap[parents.path].value[parents.key];
    }
  };

  removeObjectFromSourceMap = (uri, path) => {
    this.sourceMap[path].sources = this.sourceMap[path].sources.filter(
      (sourceUri) => sourceUri !== uri
    );

    if (this.sourceMap[path]?.sources.length === 0) {
      delete this.sourceMap[path];
    }
  };

  updateInitSourceMapValue = (path, sourceUri, parents) => {
    if (this.sourceMap[path]) {
      const sourceItem = {
        source: null,
        sourceUri
      };
      this.sourceMap[path].sources.push(sourceItem);
    }

    if (!this.isManifestBuilded) {
      this.merge({
        source: parents.source,
        manifest: this.sourceMap[parents.path].value,
        key: parents.key
      });
    }
  };

  getSource = (structuredPath, uri) => {
    return structuredPath.reduce((slice, dir) => slice[dir], this.sources[uri].manifest);
  };

  // *********************** ВНЕСЕНИЕ ИЗМЕНИЙ В МАНИФЕСТ ************************
  // ****************************************************************************

  getManifestSliceByPath = (keys) => {
    if (keys.length === 0) return this.manifest;

    let currentSlice = this.manifest;
    let parentSlice = null;
    let currentKey = null;
    for (let i = 0; i < keys.length; i++) {
      currentKey = keys[i];

      parentSlice = currentSlice;

      if (!checkIsObject(parentSlice[currentKey])) {
        parentSlice[currentKey] = {};
      }
      currentSlice = parentSlice[currentKey];
    }
    return currentSlice;
  };

  removeManifestSliceByPath = (path) => {
    const keys = path.split('/').slice(1);

    if (keys[0] === '') return;

    let currentSlice = this.manifest;
    let parentSlice = null;
    let currentKey = null;
    for (let i = 0; i < keys.length; i++) {
      currentKey = keys[i];
      parentSlice = currentSlice;
      if (checkIsObject(parentSlice[currentKey])) {
        currentSlice = parentSlice[currentKey];
      } else {
        return;
      }
    }
    delete parentSlice[currentKey];
  };

  removePrimitiveValues = (object) => {
    for (let key in object) {
      if (!checkIsObject(object[key])) {
        delete object[key];
      }
    }
  };

  updatePrimitiveValues = (manifest, path) => {
    const { sources, structuredPath } = this.sourceMap[path];
    const result = {};
    const startIndex =
      sources.findLastIndex(uri => typeof uri === 'object') + 1;

    sources.slice(startIndex).forEach((sourceUri) => {
      const source = this.getSource(structuredPath, sourceUri);
      for (let key in source) {
        if (checkIsObject(source[key])) {
          if (key in result) {
            delete result[key];
          }
        } else if (Array.isArray(source[key])) {
          this.mergeArray({ source, manifest: result, key });

          this.pushToMergeMap({
            path: createChildPath(path, key),
            sourceUri
          });
        } else {
          result[key] = source[key];
          this.pushToMergeMap({
            path: createChildPath(path, key),
            sourceUri
          });
        }
      }
    });

    Object.assign(manifest, result);
  };

  applyChanges = async() => {
    this.changes.forEach((path) => {
      if (
        this.sourceMap[path] === undefined ||
        this.sourceMap[path]?.sources?.length === 0
      ) {
        this.removeManifestSliceByPath(path); // если есть примитив то не трогаем
        return;
      }

      const { value, structuredPath } = this.sourceMap[path];

      const manifestSlice = this.getManifestSliceByPath(structuredPath);

      if (this.isManifestBuilded) {
        this.removePrimitiveValues(manifestSlice);
        this.updatePrimitiveValues(manifestSlice, path);
      } else {
        Object.assign(manifestSlice, value);
        this.sourceMap[path].value = null;
      }
    });

    this.isManifestBuilded = true;
    this.changes.clear();
  };

  // ********************* РЕГИСТРАЦИЯ И ПРИМЕНЕНИЕ ИЗМЕНИЙ *********************
  // ****************************************************************************

  // ********************************** MOUNT ***********************************

  mountEachTree = ({ sourceUri }) => {
    if (this.sources[sourceUri].imports.length) {
      this.pushToMergeMap({
        path: '/imports',
        sourceUri
      });
    }
    this.pushToMergeMap({ path: '/', sourceUri });
  };

  mountEachObject = ({
    path,
    structuredPath,
    sourceUri,
    parents
  }) => {
    this.changes.add(path);

    if (!this.sourceMap[path]) this.createSourceMap(path, structuredPath);

    this.pushObjectToSourceMap(path, sourceUri, parents);

    if (!this.mergeMap[getStorePath(path)]) {
      this.pushToMergeMap({ path, sourceUri });
    }
  };

  mountEachProp = ({ path, sourceUri, parents }) => {
    if (this.changes.has(path)) {
      this.changes.delete(path);
    }

    this.updateInitSourceMapValue(path, sourceUri, parents);

    this.pushToMergeMap({ path, sourceUri });
  };

  registerMountTree = (uri) => {
    const callbacks = {
      eachObject: this.mountEachObject.bind(this),
      eachProp: this.mountEachProp.bind(this),
      eachTree: this.mountEachTree.bind(this)
    };

    this.forEachTree({ uri, callbacks });
  };

  // Первичная сборка
  build() {
    this.rootImports.forEach((uri) => this.registerMountTree(uri));
    this.applyChanges();
  }

  // ********************************* UNMOUNT **********************************

  unmountEachTree = ({ sourceUri }) => {
    const rootPath = '/';
    this.mergeMap[rootPath] = this.mergeMap[rootPath].filter(
      (uri) => uri !== sourceUri
    );
    this.imports = this.imports.filter((uri) => uri !== sourceUri);
    this.removeRepositorySource(sourceUri);
  };

  unmountEachObject = ({ path, sourceUri }) => {
    if (!this.sourceMap[path]) return;
    this.removeObjectFromSourceMap(sourceUri, path);
    this.changes.add(path);
  };

  unmountEachProp = ({ path, sourceUri }) => {
    if (this.sourceMap[path]) {
      this.removeObjectFromSourceMap(sourceUri, path);
    }
  };

  removeSource = ({ uri }) => {
    this.errors[uri] && delete this.errors[uri];
    this.sources[uri] && delete this.sources[uri];
  };

  // ********************************* UPDATE ***********************************

  registerUpdate = async(source) => {
    const isDataSource = typeof source === 'object';
    const uri = isDataSource
      ? Object.keys(source)[0]
      : source;

    this.errors[uri] && delete this.errors[uri];
    const ownerUri = this.sources[uri]?.ownerUri;

    const rawData = isDataSource
      ? source[uri]
      : await this.pushRequest(uri);
    
    const updatedSource =  new SourceItem({ownerUri, uri, data: rawData}); 

    const sourceToUnmount = this.sources[uri];

    updatedSource.imports = updatedSource.imports.filter((importUri) => {
      const hasInUnmountSource = sourceToUnmount.imports.includes(importUri);
      const hasInManifest = Boolean(this.sources[importUri]);
      const isDoubleImport = !hasInUnmountSource && hasInManifest;

      if(isDoubleImport) {
        this.registerError(
          new PackageError(
            uri,
            `Дублирование импорта манифеста:\n${importUri}\nимпортирован в\n${this.sources[importUri].ownerUri}`
          )
        );
      }

      return !isDoubleImport;
    });

    //  Регистрируем Unmount для устаревшего source
    
    this.forEachTreeItem({
      source: sourceToUnmount.manifest,
      sourceUri: uri,
      path: '/',
      structuredPath: [],
      callbacks: { eachObject: this.unmountEachObject.bind(this) }
    });

    //  Регистрируем Mount для нового source
    this.forEachTreeItem({
      source: updatedSource.manifest,
      sourceUri: uri,
      path: '/',
      structuredPath: [],
      callbacks: { eachObject: this.mountEachObject.bind(this) }
    });

    //  Проверяем изменились ли импорты
    const importsDifferences = getImportsDifferences({
      new: updatedSource.imports,
      old: this.sources[uri].imports
    });

    for (let i = 0; i < importsDifferences.length; i++) {
      const { uri, action } = importsDifferences[i];
      if (action === 'remove') {
        // Для удаленных импортов регистрируем Unmount
        this.forEachTree({
          uri,
          callbacks: {
            eachObject: this.unmountEachObject.bind(this),
            eachTree: this.unmountEachTree.bind(this),
            eachProp: this.unmountEachProp.bind(this),
            afterEachTree: this.removeSource.bind(this)
          }
        });
      } else if (action === 'add') {
        // Для добавленных импортов регистрируем Mount
        await this.import(uri);
        this.registerMountTree(uri);
      }
    }

    this.sources[uri] = updatedSource;
  };

  onChange = async(sources) => {
    const list = sources.filter((source) => {
      const uri = typeof source === 'object'
        ? Object.keys(source)[0]
        : source;
      return this.imports.includes(uri);
    });

    this.onStartReload && this.onStartReload();

    for (let i = 0; i < list.length; i++) {
      const uri = list[i];
      await this.registerUpdate(uri);
    }
    this.applyChanges();
    this.refreshErrors();
    this.onReloaded && this.onReloaded(this);
  };

  // ********************************* HANDLERS *********************************
  // ****************************************************************************

  updateSourceData = (parserData) => {
    const { manifest, rootImports, sources, sourceMap, mergeMap, errors, imports, metamodels } = parserData;

    this.manifest = manifest;
    this.rootImports = rootImports;
    this.sources = sources;
    this.sourceMap = sourceMap;
    this.mergeMap = mergeMap;
    this.errors = errors;
    this.imports = imports;
    this.metamodels = metamodels;
  }

  clean() {
    this.rootImports = [];
    this.imports = [];
    this.sources = {};
    this.metamodels = {};

    this.sourceMap = {};
    this.mergeMap = {};

    this.manifest = {};
    this.changes = new Set();

    this.isManifestBuilded = false;
  }

  registerAfterLoadedCallback(name, func) {
    if (typeof func !== 'function') {
      logger.warn(
          () => `Функция ${name} переданная для регистрации как callback после загрузки не является функцией и не может быть зарегистрирована`
      );
      return;
    }

    if (this.manifestLoadInProgress) {
      logger.debug(
          () => `Функция ${name} зарегистрирована как callback после загрузки`
      );
      this.afterLoadedCallbacks.push({
        name: name,
        func: func
      });
    } else {
      try {
        logger.debug(() => `Вызываем функцию [${name}] сейчас т.к. манифест уже загружен`);
        func();
      } catch (err) {
        logger.warn(() => `Ошибка при вызове afterLoadedCallback ${name}`, err);
      }
    }
  }

  startLoad() {
    logger.debug(() => 'Загрузка манифеста началась');
    this.manifestLoadInProgress = true;
    this.onStartReload && this.onStartReload(parser);
  }

  stopLoad() {
    this.build();
    this.onReloaded && this.onReloaded(this);
    logger.debug(() => 'Загрузка манифеста завершена');
    this.manifestLoadInProgress = false;
    this.afterLoadedCallbacks.forEach(cb => {
      try {
        logger.debug(() => `Вызываем функцию [${cb.name}] после загрузки манифеста`);
        cb.func();
      } catch (err) {
        logger.warn(() => `Ошибка при вызове afterLoadedCallback ${cb.name}`, err);
      }
    });
  }

  checkAwaitedPackages() {
    return true;
  }

  checkLoaded() {
    return true;
  }
}

const parser = new Parser();

export default parser;
