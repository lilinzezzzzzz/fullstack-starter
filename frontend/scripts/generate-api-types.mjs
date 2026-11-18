import { execFileSync } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import openapiTS, { astToString } from 'openapi-typescript';
import { configFile } from './project-config.mjs';

const projectRoot = fileURLToPath(new URL('../../', import.meta.url));
const args = process.argv.slice(2);
const check = args.includes('--check');
const outputIndex = args.indexOf('--output');
const output =
  outputIndex >= 0
    ? resolve(args[outputIndex + 1])
    : resolve(projectRoot, 'frontend/src/types/api.generated.d.ts');

// 仅翻译用于生成注释的元数据，保留接口字段、类型名称和引用路径。
const commentTranslations = new Map([
  ['Get Health', '获取健康状态'],
  ['Get Hello', '获取 Hello 欢迎语'],
  ['ErrorDetail', '错误详情条目'],
  ['Field', '字段'],
  ['Message', '消息'],
  ['ErrorResponse', '错误响应'],
  ['Code', '错误码'],
  ['Details', '详情'],
  ['Trace Id', '链路标识'],
  ['HealthResponse', '健康检查响应'],
  ['Database', '数据库'],
  ['Status', '状态'],
  ['HelloResponse', 'Hello 欢迎语响应'],
  ['Successful Response', '请求成功'],
  ['Bad Request', '请求无效'],
  ['Forbidden', '禁止访问'],
  ['Not Found', '未找到资源'],
  ['Unprocessable Content', '请求内容无法处理'],
  ['Internal Server Error', '服务器内部错误'],
  ['Service Unavailable', '服务不可用'],
]);

try {
  const schema = execFileSync(
    'uv',
    [
      'run',
      '--directory',
      resolve(projectRoot, 'backend'),
      'python',
      '-m',
      'entrypoints.cli',
      '--config',
      configFile,
      'export-openapi',
    ],
    { encoding: 'utf8', maxBuffer: 10 * 1024 * 1024 },
  );
  const localizedSchema = JSON.parse(schema, (key, value) =>
    ['title', 'summary', 'description'].includes(key) && typeof value === 'string'
      ? (commentTranslations.get(value) ?? value)
      : value,
  );
  const ast = await openapiTS(localizedSchema);
  const contents = '// 由 pnpm api:types 生成，请勿手动编辑。\n' + astToString(ast);
  if (check) {
    const current = await readFile(output, 'utf8').catch((error) => {
      if (error.code === 'ENOENT') return null;
      throw error;
    });
    if (current !== contents) {
      console.error('API types are stale. Run: pnpm --dir frontend api:types');
      process.exitCode = 1;
    } else {
      console.log('API types are current.');
    }
  } else {
    await mkdir(dirname(output), { recursive: true });
    await writeFile(output, contents);
    console.log('Generated API types:', output);
  }
} catch (error) {
  console.error('Could not generate API types:', error.message);
  process.exitCode = 1;
}
