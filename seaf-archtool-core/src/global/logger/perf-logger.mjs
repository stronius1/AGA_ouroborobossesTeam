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
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber

  Contributors:
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2025
*/

export class PerformanceLogger {
    constructor(logger, recorder) {
        this.logger = logger;
        this.recorder = recorder;
    }

    getTimeStamp() {
        return performance.now();
    }

    getMemory() {
        return performance.memory.usedJSHeapSize;
    }

    getDatasetLogger(dataset) {
        return new DatasetLogger(this.logger, this.getTimeStamp, this.getMemory, this.recorder, dataset);
    }

    getJsonataLogger(functionId, params) {
        return new JsonataLogger(this.logger, this.getTimeStamp, this.getMemory, this.recorder, functionId, params);
    }

    getRequestLogger(uri) {
        return new RequestLogger(this.logger, this.getTimeStamp, this.getMemory, uri);
    }

    getGenericLogger() {
        return new GenericLogger(this.logger, this.getTimeStamp, this.getMemory);
    }
}

class CommonLogger {
    stats = {};

    constructor(logger, getTimeStamp, getMemory) {
        this.logger = logger;
        this.getTimeStamp = getTimeStamp;
        this.getMemory = getMemory;
    }

    setStart() {
        this.stats.startTime = this.getTimeStamp();
        this.stats.startMemory = this.getMemory();
    }

    setEnd() {
        this.stats.endTime = this.getTimeStamp();
        this.stats.endMemory = this.getMemory();
    }

    statAsText() {
        return [
            {title: 'Execution time:', obj: `${(this.stats.endTime - this.stats.startTime).toFixed(2)} ms`},
            {
                title: 'Heap usage change:',
                obj: `${((this.stats.endMemory - this.stats.startMemory) / 1024).toFixed(2)} KB`
            },
            {title: 'Current heap usage:', obj: `${((this.stats.endMemory / 1024 / 1024).toFixed(2))} MB`}
        ];
    }
}

class GenericLogger extends CommonLogger {
    constructor(logger, getTimeStamp, getMemory) {
        super(logger, getTimeStamp, getMemory);
    }

    setEnd() {
        super.setEnd();
        this.logger.trace('generic-perf', () => [
            ...super.statAsText()
        ]);
    }
}

class RequestLogger extends CommonLogger {
    constructor(logger, getTimeStamp, getMemory, uri) {
        super(logger, getTimeStamp, getMemory);
        this.uri = uri;
    }

    setEnd() {
        super.setEnd();
        this.logger.trace('request-perf', () => [
                `URI: ${this.uri}`,
                ...super.statAsText()
            ]
        );
    }
}

class JsonataLogger extends CommonLogger {
    constructor(logger, getTimeStamp, getMemory, recorder, functionId, params) {
        super(logger, getTimeStamp, getMemory);
        this.functionId = functionId;
        this.params = params;
        this.recorder = recorder;
    }

    setEnd(result) {
        super.setEnd();
        this.logger.trace('jsonata-perf', () => [
            `JSONata function: ${this.functionId}`,
            this.params ? {title: 'Parameters:', obj: this.params} : undefined,
            result ? {title: 'Result:', obj: result} : undefined,
            ...super.statAsText()
        ]);
        this.recorder?.reportJsonata(this.functionId, this.stats.endTime - this.stats.startTime);
    }
}

class DatasetLogger extends CommonLogger {
    constructor(logger, getTimeStamp, getMemory, recorder, dataset) {
        super(logger, getTimeStamp, getMemory);
        this.dataset = dataset;
        this.recorder = recorder;
    }

    setStart() {
        super.setStart();
        this.recorder?.addDataset(this.dataset);
        this.logger.debug('datasets-perf', () => `Dataset ${this.dataset} loading...`);
    }

    setEnd() {
        super.setEnd();
        this.logger.debug('datasets-perf', () => [
            `Dataset ${this.dataset} loaded`,
            ...super.statAsText()
        ]);
        this.recorder?.removeDataset(this.dataset);
    }
}
