import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { cp, mkdir, mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { createServer } from 'node:net';
import { basename, dirname, join, resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { clearTimeout, setTimeout } from 'node:timers';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';
import { stringify } from 'smol-toml';
import { configFile as canonicalConfig, readProjectSettings } from './project-config.mjs';

const require = createRequire(import.meta.url);
const projectRoot = fileURLToPath(new URL('../../', import.meta.url));
const frontendRoot = join(projectRoot, 'frontend');
const { values } = parseArgs({ options: { config: { type: 'string' } } });
// 唯一可省略的参数是引导文件路径，应用配置值均不可省略。
const source = values.config === undefined ? canonicalConfig : resolve(projectRoot, values.config);
const settings = readProjectSettings(source);
const parent = settings.testing.temporary_directory;
await mkdir(parent, { recursive: true });
const workDir = await mkdtemp(join(parent, 'agent-task.'));
const configFile = join(workDir, 'app.toml');
const children = new Set();
let interrupted = false;
let passed = false;

function stop(child, signal = 'SIGINT') {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  try {
    process.kill(-child.pid, signal);
  } catch (error) {
    if (error.code !== 'ESRCH') throw error;
  }
}

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.once(signal, () => {
    interrupted = true;
    for (const child of children) stop(child);
  });
}

async function run(command, argv, options = {}) {
  if (interrupted) throw new Error('Interrupted');
  const child = spawn(command, argv, {
    cwd: projectRoot,
    stdio: 'inherit',
    detached: true,
    ...options,
  });
  children.add(child);
  let timedOut = false;
  let forceStop;
  const timeout = setTimeout(() => {
    timedOut = true;
    stop(child);
    forceStop = setTimeout(
      () => stop(child, 'SIGKILL'),
      settings.testing.termination_grace_seconds * 1000,
    );
  }, settings.testing.command_timeout_seconds * 1000);
  try {
    const [code] = await once(child, 'exit');
    if (timedOut) throw new Error(`${command} exceeded the configured command timeout`);
    if (code !== 0) throw new Error(`${command} exited with ${code}`);
  } finally {
    children.delete(child);
    clearTimeout(timeout);
    clearTimeout(forceStop);
  }
}

function packageCLI(name, path) {
  return join(dirname(require.resolve(`${name}/package.json`)), path);
}

async function unusedPort() {
  const socket = createServer();
  socket.listen(0, settings.testing.host);
  await once(socket, 'listening');
  const port = socket.address().port;
  await new Promise((resolve, reject) =>
    socket.close((error) => (error ? reject(error) : resolve())),
  );
  return port;
}

try {
  settings.frontend_dir = join(workDir, 'dist');
  settings.frontend_clean_output = false;
  await writeFile(configFile, stringify(settings));
  await run(process.execPath, [packageCLI('typescript', 'bin/tsc'), '--noEmit'], {
    cwd: frontendRoot,
  });
  const generatedViteConfig = join(workDir, 'vite.config.mjs');
  const viteFactory = pathToFileURL(join(frontendRoot, 'scripts/vite-settings.mjs')).href;
  const settingsReader = pathToFileURL(join(frontendRoot, 'scripts/project-config.mjs')).href;
  await writeFile(
    generatedViteConfig,
    `
import { createViteSettings } from ${JSON.stringify(viteFactory)};
import { readProjectSettings } from ${JSON.stringify(settingsReader)};
export default createViteSettings(readProjectSettings(${JSON.stringify(configFile)}));
`,
  );
  await run(
    process.execPath,
    [packageCLI('vite', 'bin/vite.js'), 'build', '--config', generatedViteConfig],
    { cwd: frontendRoot },
  );
  const port = await unusedPort();
  const host = settings.testing.host.includes(':')
    ? `[${settings.testing.host}]`
    : settings.testing.host;
  const baseURL = `http://${host}:${port}`;
  settings.data_dir = join(workDir, 'data');
  settings.backup_directory = join(workDir, 'backups');
  settings.serve_frontend = true;
  settings.logging.directory = join(workDir, 'logs');
  settings.logging.console = false;
  settings.allowed_origins = [baseURL];
  settings.allowed_hosts = [settings.testing.host];
  await writeFile(configFile, stringify(settings));
  await run('uv', [
    'run',
    '--directory',
    'backend',
    'python',
    '-m',
    'entrypoints.cli',
    '--config',
    configFile,
    'db-upgrade',
  ]);
  const runtimeFile = join(workDir, 'playwright.json');
  await writeFile(
    runtimeFile,
    JSON.stringify({
      baseURL,
      outputDir: join(workDir, 'results'),
      testing: settings.testing,
    }),
  );
  const generatedConfig = join(workDir, 'playwright.config.mjs');
  const testFactory = pathToFileURL(join(frontendRoot, 'scripts/playwright-settings.mjs')).href;
  // 服务管理目录固定为项目根的 .run；复制后端以隔离整份项目的运行状态。
  const serviceRoot = join(workDir, 'service-project');
  const serviceBackend = join(serviceRoot, 'backend');
  await cp(join(projectRoot, 'backend'), serviceBackend, {
    recursive: true,
    filter: (source) => {
      const name = basename(source);
      return (
        !['.venv', '__pycache__', '.pytest_cache', '.ruff_cache', 'tests'].includes(name) &&
        !name.startsWith('.env') &&
        !name.startsWith('.secrets')
      );
    },
  });
  await symlink(join(projectRoot, 'backend/.venv'), join(serviceBackend, '.venv'), 'dir');
  await cp(join(projectRoot, 'entrypoints'), join(serviceRoot, 'entrypoints'), { recursive: true });
  const serviceEntry = join(serviceRoot, 'entrypoints/service.sh');
  const serviceScript = (await readFile(serviceEntry, 'utf8'))
    .replace(
      /^server_host=.*$/m,
      () => `server_host='${settings.testing.host.replaceAll("'", "'\\''")}'`,
    )
    .replace(/^server_port=[0-9]+$/m, `server_port=${port}`);
  await writeFile(serviceEntry, serviceScript);
  const serviceCommand = `sh '${serviceEntry.replaceAll("'", "'\\''")}' run --config '${configFile.replaceAll("'", "'\\''")}'`;
  await writeFile(
    generatedConfig,
    `
import { createPlaywrightSettings } from ${JSON.stringify(testFactory)};
import { readFileSync } from 'node:fs';
const runtime = JSON.parse(readFileSync(${JSON.stringify(runtimeFile)}, 'utf8'));
const config = createPlaywrightSettings(runtime.testing);
export default {
  ...config,
  testDir: ${JSON.stringify(join(frontendRoot, 'e2e'))},
  outputDir: runtime.outputDir,
  use: { ...config.use, baseURL: runtime.baseURL },
  webServer: {
    command: ${JSON.stringify(serviceCommand)},
    cwd: ${JSON.stringify(serviceRoot)},
    url: runtime.baseURL + '/api/health',
    reuseExistingServer: false,
    timeout: runtime.testing.command_timeout_seconds * 1000,
    gracefulShutdown: {
      // 使用 Uvicorn 原生 Ctrl+C 路径并等待退出，不额外接管最终日志收尾。
      signal: 'SIGINT',
      timeout: runtime.testing.termination_grace_seconds * 1000,
    },
  },
};
`,
  );
  await run(
    process.execPath,
    [packageCLI('@playwright/test', 'cli.js'), 'test', '--config', generatedConfig],
    { cwd: frontendRoot },
  );
  passed = true;
} catch (error) {
  console.error(error.message);
  console.error(
    await readFile(join(workDir, 'logs', settings.logging.filename), 'utf8').catch(() => ''),
  );
  console.error('Diagnostics retained:', workDir);
  process.exitCode = interrupted ? 130 : 1;
} finally {
  const owned = [...children];
  const exits = owned.map((child) => once(child, 'exit').catch(() => {}));
  for (const child of owned) stop(child);
  await Promise.race([
    Promise.all(exits),
    delay(settings.testing.termination_grace_seconds * 1000),
  ]);
  for (const child of owned) stop(child, 'SIGKILL');
  await Promise.all(exits);
  if (passed && !settings.testing.keep_artifacts) {
    await rm(workDir, { recursive: true, force: true });
  } else if (passed) {
    console.log('Verification artifacts:', workDir);
  }
}
