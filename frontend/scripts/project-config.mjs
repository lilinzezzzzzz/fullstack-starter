import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const projectRoot = fileURLToPath(new URL('../../', import.meta.url));
// 引导文件路径，不作为应用参数的回退值。
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
  // 不得向浏览器暴露完整服务端配置或其文件系统路径。
  return {
    __CLIENT_CONFIG__: JSON.stringify(settings.client),
    __APPLICATION_INFO__: JSON.stringify({
      title: settings.application.title,
      version: settings.application.version,
    }),
  };
}
