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
      Saveliy Zaznobin <zaznobins@yandex.ru>, Sber - 2024
*/

import { EventEmitter } from 'node:events';
import { Worker } from 'worker_threads';

export class WorkerStack {
    constructor(workerCount, source, workerTimeout, requestTimeout) {
        this.stack = [];
        this.max = workerCount;
        this.source = source;
        this.workerTimeout = workerTimeout;
        this.queueTimeout = requestTimeout;
        this.taskQueue = [];
        this.emitter = new EventEmitter();
        this.dequeue = this.dequeue.bind(this);
        this.emitter.on('ready', this.dequeue);
        if (source) {
            for (let i = 0; i < workerCount; i++) {
                this.stack.push(new Worker(source));
            }
        }
    }
    
    async execute(data) {
        const timeout = new Promise((_resolve, reject) => {
            setTimeout(() => {
                reject('Queue timeout');
            }, this.queueTimeout);
        });
        const result = new Promise((resolve, reject) => {
            this.retrieve().then((worker) => {
                worker.removeAllListeners();
                const controller = setTimeout(() => {
                    worker.terminate();
                    this.put(new Worker(this.source));
                }, this.workerTimeout);
                worker.on('exit', () => {
                    clearTimeout(controller);
                    this.put(new Worker(this.source));
                    reject('Worker terminated');
                });
                worker.on('message', (outcome) => {
                    clearTimeout(controller);
                    this.put(worker);
                    resolve(outcome);
                });
                worker.on('error', (error) => {
                    clearTimeout(controller);
                    this.put(worker);
                    reject(error);
                });
                worker.postMessage(data);
            });
        });
        return Promise.race([timeout, result]);
    }
    
    dequeue() {
        while (this.taskQueue.length > 0 && this.stack.length > 0) {
            this.taskQueue.shift()(this.stack.pop());
        }
    }
    
    put(worker) {
        if (this.stack.length < this.max) {
            this.stack.push(worker);
            if (this.stack.length === 1) {
                this.emitter.emit('ready');
            }
            return true;
        } else return false;
    }
    
    async retrieve() {
        let worker = this.stack.pop();
        if (!worker) {
            let request;
            const promise = new Promise((resolve) => {
                request = resolve;
            });
            this.taskQueue.push(request);
            worker = await promise;
        }
        return worker;
    }
}