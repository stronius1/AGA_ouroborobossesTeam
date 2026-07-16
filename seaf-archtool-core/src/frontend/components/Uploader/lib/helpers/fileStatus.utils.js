/*
  Copyright (C) 2026 Sber

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

  Maintainers:
      Nikolay Temnyakov <temnjakovn@gmail.com>, Sber - 2026
*/

const POLL_INTERVAL_MS = 50000;

const TERMINAL_UPLOAD_STATUSES = new Set(['STORED_S3', 'UPLOAD_REJECTED', 'EXPIRED']);
const ACTIVE_VALIDATOR_STATUSES = new Set(['PENDING', 'RETRY']);

export function isTerminalUploadStatus(status) {
  return TERMINAL_UPLOAD_STATUSES.has(String(status ?? '').toUpperCase());
}

function hasActiveValidator(validatorsMap) {
  if (!validatorsMap || typeof validatorsMap !== 'object') return false;
  return Object.values(validatorsMap).some(validator =>
    ACTIVE_VALIDATOR_STATUSES.has(String(validator?.status ?? '').toUpperCase())
  );
}

export function isUploadValidationActive(file) {
  if (!file) return false;
  return !isTerminalUploadStatus(file.status) || hasActiveValidator(file.uploadValidators);
}

export function isDownloadValidationActive(file) {
  if (!file) return false;
  if (file.downloadValidationRequested && !file.downloadValidatedAt) return true;
  return hasActiveValidator(file.downloadValidators);
}

export function isValidationActive(file) {
  return isUploadValidationActive(file) || isDownloadValidationActive(file);
}

export function pollDelay() {
  return POLL_INTERVAL_MS;
}
