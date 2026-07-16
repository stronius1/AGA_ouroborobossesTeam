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
      Temnyakov Nikolay <temnjakovn@gmail.com>, Sber

  Contributors:
      Temnyakov Nikolay <temnjakovn@gmail.com>, Sber - 2026
*/

const VALIDATOR_STATUS_FAILED = 'FAILED';

const FAILURE_REASON_RECOVERABLE = 'RECOVERABLE';
const FAILURE_REASON_PERMANENT = 'PERMANENT';

const FILE_STATUS_UPLOAD_REJECTED = 'UPLOAD_REJECTED';

export const FailureCategory = Object.freeze({
    NONE: 'NONE',
    RECOVERABLE: 'RECOVERABLE',
    PERMANENT: 'PERMANENT'
});

function validatorEntries(validators) {
    if (!validators || typeof validators !== 'object') return [];
    return Object.values(validators).filter(Boolean);
}

function hasFailedWith(validators, reason) {
    return validatorEntries(validators).some(
        (v) => v.status === VALIDATOR_STATUS_FAILED && v.failureReason === reason
    );
}

function failureCategory(validators) {
    if (hasFailedWith(validators, FAILURE_REASON_PERMANENT)) return FailureCategory.PERMANENT;
    if (hasFailedWith(validators, FAILURE_REASON_RECOVERABLE)) return FailureCategory.RECOVERABLE;
    return FailureCategory.NONE;
}

export function uploadFailureCategory(file) {
    if (!file) return FailureCategory.NONE;
    return failureCategory(file.uploadValidators);
}

export function downloadFailureCategory(file) {
    if (!file) return FailureCategory.NONE;
    return failureCategory(file.downloadValidators);
}

export function canRecheckUpload(file) {
    if (!file) return false;
    if (file.status !== FILE_STATUS_UPLOAD_REJECTED) return false;
    return uploadFailureCategory(file) === FailureCategory.RECOVERABLE;
}

export function canRecheckDownload(file) {
    if (!file) return false;
    if (file.downloadValidationRequested) return false;
    if (file.downloadValidatedAt) return false;
    return downloadFailureCategory(file) === FailureCategory.RECOVERABLE;
}
