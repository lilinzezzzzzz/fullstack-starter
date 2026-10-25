import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { existsSync } from 'node:fs';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { createServer } from 'node:net';
import { dirname, join, resolve } from 'node:path';
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
// The only omitted argument is a bootstrap file locator, never an application value.
const source = values.config === undefined ? canonicalConfig : resolve(projectRoot, values.config);
const settings = readProjectSettings(source);
const parent = settings.testing.temporary_directory;
await mkdir(parent, { recursive: true });
const workDir = await mkdtemp(join(parent, 'agent-task.'));
const configFile = join(workDir, 'app.toml');
const pidFile = join(workDir, 'service.pid');
const children = new Set();
let interrupted = false;
let passed = false;

function stop(child, signal = 'SIGTERM') {
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

async function run(command, argv, { allowInterrupted = false, ...options } = {}) {
  if (interrupted && !allowInterrupted) throw new Error('Interrupted');
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
export default createViteSettings(readProjectSettings(${JSON.stringify(source)}));
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
  settings.server.port = port;
  settings.server.host = settings.testing.host;
  settings.logging.directory = join(workDir, 'logs');
  settings.logging.console = false;
  settings.service.pid_file = pidFile;
  settings.allowed_origins = [baseURL];
  settings.allowed_hosts = [settings.testing.host];
  await writeFile(configFile, stringify(settings));
  await run('uv', [
    'run',
    '--directory',
    'backend',
    'python',
    '-m',
    'app.cli',
    '--config',
    configFile,
    'db-upgrade',
  ]);
  await run('sh', ['scripts/service.sh', 'start', '--config', configFile]);

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
  console.error(await readFile(join(workDir, 'logs/service.log'), 'utf8').catch(() => ''));
  console.error('Diagnostics retained:', workDir);
  process.exitCode = interrupted ? 130 : 1;
} finally {
  if (existsSync(pidFile)) {
    try {
      await run('sh', ['scripts/service.sh', 'stop', '--config', configFile], {
        allowInterrupted: true,
      });
    } catch (error) {
      passed = false;
      process.exitCode = 1;
      console.error('Could not stop test service:', error.message, workDir);
    }
  }
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
