# 前端规则

适用于 `frontend/`；同时遵循[根目录规则](../AGENTS.md)。

## 页面与客户端

- 沿用 React、TypeScript、React Router、TanStack Query、Ant Design 与 CSS Modules。页面放 `src/pages/`，可复用组件放 `src/components/`，HTTP 边界放 `src/api/`，查询编排放 `src/hooks/`；局部状态就地维护，不为 Hello 示例增加通用状态框架。
- Hello 页同时验证真实 Hello API 与数据库健康检查，保留加载、成功、错误与重试状态；不通过静态假数据掩盖连接失败。
- 请求复用 `src/api/client.ts`，保留 AbortSignal 传播、超时与调用方取消的区分、定时器和监听器清理。TanStack Query 的 signal 传至实际请求；重试与缓存取显式客户端配置，写请求重试次数固定约束为 0。
- 错误从标准错误体读取 `message`、`code`、`trace_id`；不依赖 `X-Trace-ID`。编译期类型断言不能替代运行时错误处理。
- 保留语义化交互、键盘焦点、窄屏布局与无横向溢出；修改状态呈现或交互后更新相关页面测试。Ant Design 主题参数只作用于组件，页面品牌与全局 CSS 不会自动随之换肤。

## 配置、构建与生成文件

- Node 版本遵循根 `.node-version`，pnpm 版本遵循 `package.json` 的 packageManager/engines；保留 `pnpm-lock.yaml`，不用 npm/yarn 替换。前端命令依赖已安装的后端环境。
- `scripts/project-config.mjs` 调用 Python CLI 完整校验 TOML；Vite、Playwright 与类型工具共用该入口。不能增加 `VITE_*`、`import.meta.env` 或独立 TOML 解析作为应用参数来源。
- 浏览器只注入 `client` 和应用标题/版本，不注入完整配置、服务端路径或访问允许列表。修改公开配置要同步后端 Schema、构建注入、生成类型与配置文档。
- `src/types/api.generated.d.ts` 通过 `pnpm --dir frontend api:types` 生成；禁止手工编辑或用 Prettier 改写。`api:types:check` 发现过期应失败且不改写文件。
- 构建输出路径与清空限制遵守 Python 路径校验；不绕过符号链接和源码保护。验证构建使用本次临时 TOML 与输出目录，不重建或清空日常 `frontend/dist/`。

## 验证

从项目根目录运行，选择与改动相关的检查；`build` 包含 TypeScript 检查。

`format:check` 与 `format` 共用检查/整理范围，除前端文件外，还包括根 README、`docs/` 下全部 Markdown 与各级 `AGENTS.md`；同时读取 `.prettierignore` 与根 `.gitignore`，排除生成类型、锁文件、依赖、构建和私有运行产物。

```bash
pnpm --dir frontend format:check
pnpm --dir frontend lint
pnpm --dir frontend typecheck
pnpm --dir frontend api:types:check
pnpm --dir frontend test:e2e
```

- 构建与 E2E 的完整命令和配置选择见 [README](../README.md#接口类型与验证)。页面流程只用 `test:e2e` 入口，不直接执行 Playwright test 绕过隔离运行器。
- E2E 使用独占临时 TOML、数据库、日志、构建目录和服务端口，经 sh 入口启动自有服务，由 Playwright 等待健康检查并优雅关闭；不复用日常服务。
- Chromium 为当前自动化基线，安装匹配的浏览器后再运行；尊重 screenshot/trace/keep_artifacts 配置。成功且 keep_artifacts=false 时清理，成功且为 true 时保留产物，失败时始终保留诊断并报告路径。未运行浏览器测试时，不把类型、lint 或构建通过表述为页面行为通过。
