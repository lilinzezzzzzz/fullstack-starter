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
  ['ClientSettings', '客户端配置'],
  ['Mutation Retry Attempts', '写操作重试次数'],
  ['Query Cache Seconds', '查询缓存保留时间（秒）'],
  ['Query Retry Attempts', '查询重试次数'],
  ['Query Retry Delay Seconds', '查询重试间隔（秒）'],
  ['Query Stale Seconds', '查询数据保鲜时间（秒）'],
  ['Refetch On Mount', '组件挂载时重新请求'],
  ['Refetch On Reconnect', '网络重连时重新请求'],
  ['Refetch On Window Focus', '窗口获得焦点时重新请求'],
  ['Request Timeout Seconds', '请求超时时间（秒）'],
  ['Retry Min Status', '可重试的最小 HTTP 状态码'],
  ['Retry Network Errors', '网络错误时重试'],
  ['Theme Border Radius', '主题圆角半径'],
  ['Theme Font Family', '主题字体族'],
  ['Theme Font Size', '主题字号'],
  ['Theme Primary Color', '主题主色'],
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
      'app.cli',
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
