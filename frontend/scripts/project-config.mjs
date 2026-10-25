import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const projectRoot = fileURLToPath(new URL('../../', import.meta.url));
// A bootstrap locator, not an application parameter fallback.
export const configFile = resolve(projectRoot, 'configs/app.toml');

export function readProjectSettings(path) {
  const output = execFileSync(
    'uv',
    [
      'run',
      '--directory',
      resolve(projectRoot, 'backend'),
      'python',
      '-m',
      'app.cli',
      '--config',
      path,
      'export-settings',
    ],
    { encoding: 'utf8', maxBuffer: 10 * 1024 * 1024 },
  );
  return JSON.parse(output);
}

export function browserDefinitions(settings) {
  // Never publish the complete server configuration or its filesystem paths.
  return {
    __CLIENT_CONFIG__: JSON.stringify(settings.client),
    __APPLICATION_INFO__: JSON.stringify({
      title: settings.application.title,
      version: settings.application.version,
    }),
  };
}
