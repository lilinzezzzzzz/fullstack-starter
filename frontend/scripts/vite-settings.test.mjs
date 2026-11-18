import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { readViteDevSettings } from './vite-settings.mjs';

const validFields = {
  host: '"127.0.0.1"',
  port: '5173',
  proxy_target: '"http://127.0.0.1:18001"',
  strict_port: 'true',
  change_origin: 'true',
};

function writeConfig(context, fields) {
  const directory = mkdtempSync(join(tmpdir(), 'agent-task.'));
  context.after(() => rmSync(directory, { recursive: true, force: true }));
  const file = join(directory, 'vite.toml');
  const assignments = Object.entries(fields).map(([field, value]) => `${field} = ${value}`);
  writeFileSync(file, `${assignments.join('\n')}\n`, 'utf8');
  return file;
}

test('maps TOML into Vite server options and preserves a false change_origin', (context) => {
  const file = writeConfig(context, { ...validFields, change_origin: 'false' });
  assert.deepEqual(readViteDevSettings(file), {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: { '/api': { target: 'http://127.0.0.1:18001', changeOrigin: false } },
  });
});

for (const field of Object.keys(validFields)) {
  test(`rejects a missing ${field}`, (context) => {
    const fields = { ...validFields };
    delete fields[field];
    const file = writeConfig(context, fields);
    assert.throws(() => readViteDevSettings(file), new RegExp(`: ${field} must be`));
  });
}

test('rejects unknown fields', (context) => {
  const file = writeConfig(context, { ...validFields, unexpected: 'true' });
  assert.throws(() => readViteDevSettings(file), /unknown fields unexpected/);
});

const invalidFields = [
  ['host', '""'],
  ['port', '0'],
  ['port', '65536'],
  ['port', '5173.0'],
  ['port', '"5173"'],
  ['port', 'true'],
  ['proxy_target', '"ftp://127.0.0.1"'],
  ['proxy_target', '"http://"'],
  ['proxy_target', '"http://user@127.0.0.1"'],
  ['strict_port', 'false'],
  ['change_origin', '"false"'],
];

for (const [field, value] of invalidFields) {
  test(`rejects ${field} = ${value}`, (context) => {
    const file = writeConfig(context, { ...validFields, [field]: value });
    assert.throws(() => readViteDevSettings(file), new RegExp(`: ${field} must be`));
  });
}
