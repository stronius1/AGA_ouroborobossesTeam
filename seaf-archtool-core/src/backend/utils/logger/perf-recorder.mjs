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

import { recorder } from '../../../global/logger/perf-recorder.mjs';
import { profileLogger } from '@back/utils/logger/constLoggers.mjs';
import {getLoggerWithTag} from '@global/logger/v2/logger.mjs';

const logger = getLoggerWithTag('perf-recorder');

const object = {};
const INTERVAL = process.env.VUE_APP_DOCHUB_PERF_INTERVAL || 30000;

const INIT_NUMBERS = {
	scavenge: 0,
	markCompact: 0,
	markSweep: 0
};

const INIT_DURATION = {
	scavenge: 0,
	markCompact: 0,
	markSweep: 0
};

const currentDatasets = new Map();

let accumNum = {...INIT_NUMBERS};
let accumDur = {...INIT_DURATION};

const KIND_LIST = {
	1: 'scavenge',
	4: 'markCompact',
	8: 'markSweep'
};

export default Object.assign(object, recorder, {
	observer: new PerformanceObserver((list) => {
		for (const entry of list.getEntries()) {
			object.reportGc(entry.detail.kind, entry.duration);
		}
	}),
	profileLogger,
	reportGc(kind, duration) {
		const ops = KIND_LIST[kind];
		accumNum[ops]++;
		accumDur[ops] += duration;
	},
	addDataset(dataset) {
		currentDatasets.set(dataset, currentDatasets.has(dataset) ? currentDatasets.get(dataset) + 1 : 1);
	},
	removeDataset(dataset) {
		const newValue = currentDatasets.get(dataset) - 1;
		if (newValue === 0) currentDatasets.delete(dataset);
		else currentDatasets.set(dataset, newValue);
	},
    start() {
        if (!this.observer) return;
		if (!profileLogger) {
			logger.info(() => 'Perf recorder observe is not running because the logger for it has not been created.');
			return;
		}
        this.observer.observe({ entryTypes: ['gc'] });
        setInterval(() => {
            const mem = process.memoryUsage();
			profileLogger.trace('gc', () => `Scavenge: ${accumNum.scavenge} ops, ${accumDur.scavenge.toFixed(2)} ms`);
			profileLogger.trace('gc', () => `MarkCompact: ${accumNum.markCompact} ops, ${accumDur.markCompact.toFixed(2)} ms`);
			profileLogger.trace('gc', () => `MarkSweep: ${accumNum.markSweep} ops, ${accumDur.markSweep.toFixed(2)} ms`);
            for (const funcId in this.jsonataStore) {
				profileLogger.trace('jsonata-func-perf', () => `${funcId} called ${this.jsonataStore[funcId].count} times, took ${this.jsonataStore[funcId].duration.toFixed(2)} ms`, 'jsonata');
                delete this.jsonataStore[funcId];
            }
			if (currentDatasets.size) {
				let data = '';
				currentDatasets.forEach((value, key) => {
					data += `${key}: ${value}; `;
				});
				profileLogger.trace('datasets', () => `Current datasets: ${data}`);
			}
			profileLogger.trace('memory', () => `RSS: ${(mem.rss / 1024 / 1024).toFixed(2)} MB`);
			profileLogger.trace('memory', () => `Used heap: ${(mem.heapUsed / 1024 / 1024).toFixed(2)} MB`);
            accumNum = {...INIT_NUMBERS};
            accumDur = {...INIT_DURATION};
        }, INTERVAL);
    }
});
