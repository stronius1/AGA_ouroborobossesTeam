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
      Temnyakov Nikolay <temnjakovn@gmail.com>, Sber - 2026
*/

export const HIGHLIGHT_TYPE = Object.freeze({
  NEW: 'new',
  UPDATED: 'updated',
  ERROR: 'error'
});

const REJECT_TOKEN = 'REJECT';
const FAILED_TOKEN = 'FAILED';
const EXPIRED_TOKEN = 'EXPIRED';
const PASSED_TOKEN = 'PASSED';
const READY_TOKENS = ['STORED', 'READY', 'AVAILABLE'];

export function isRejectedStatus(upperStatus) {
  return upperStatus.includes(REJECT_TOKEN) || upperStatus.includes(FAILED_TOKEN);
}

export function isTerminalErrorStatus(upperStatus) {
  return upperStatus.includes(REJECT_TOKEN) || upperStatus.includes(EXPIRED_TOKEN);
}

export function isReadyStatus(upperStatus) {
  return READY_TOKENS.some(token => upperStatus.includes(token));
}

export function isPassedStatus(upperStatus) {
  return upperStatus.includes(PASSED_TOKEN);
}

const SIGNATURE_FIELDS = [
  'status',
  'uploadValidated',
  'downloadValidatedAt',
  'downloadValidationRequested'
];

export function highlightSignature(file) {
  if (!file) return '';

  const payload = {};
  for (const field of SIGNATURE_FIELDS) {
    payload[field] = file[field] ?? null;
  }
  payload.uploadValidators = validatorStatusMap(file.uploadValidators);
  payload.downloadValidators = validatorStatusMap(file.downloadValidators);

  return JSON.stringify(payload);
}

function validatorStatusMap(validators) {
  if (!validators) return null;
  return Object.keys(validators).reduce((acc, key) => {
    acc[key] = validators[key]?.status ?? null;
    return acc;
  }, {});
}
