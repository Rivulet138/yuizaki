import assert from 'node:assert/strict';
import test from 'node:test';

import { resolveMcpPort } from './config.mjs';

test('uses a valid configured port', () => {
  assert.equal(resolveMcpPort('7789'), 7789);
});

test('uses the default for missing or malformed values', () => {
  assert.equal(resolveMcpPort(), 7777);
  assert.equal(resolveMcpPort('not-a-port'), 7777);
});

test('rejects ports outside the TCP range', () => {
  assert.equal(resolveMcpPort('0'), 7777);
  assert.equal(resolveMcpPort('65536'), 7777);
});
