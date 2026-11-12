# fullstack-starter

面向本地、单用户、单机应用的 FastAPI + SQLite + React 脚手架。默认由单 worker FastAPI 提供页面和 API；V1 只有 Hello 欢迎页、Hello API 与数据库健康检查，不创建业务表。

| 需要做什么           | 入口                                              |
| -------------------- | ------------------------------------------------- |
| 安装并运行           | [首次运行](#首次运行)                             |
| 创建独立的新项目     | [项目创建指南](docs/project-creation.md)          |
| 对齐正在开发的项目   | [已有项目架构对齐指南](docs/project-alignment.md) |
| 了解目录、分层与契约 | [当前设计](docs/design.md)                        |
| 修改配置             | [配置约定](docs/configuration.md)                 |
| 备份、恢复或编写迁移 | [数据库维护与迁移](docs/database.md)              |
| 查看历史实测结果     | [实现与验证记录](docs/history.md)                 |

## 技术栈

- 后端：Python、uv、FastAPI、Pydantic v2、SQLAlchemy 2.0 async、aiosqlite、SQLite、Alembic、Loguru。
- 前端：Node.js、pnpm、React、TypeScript、Vite、React Router、TanStack Query、Ant Design、CSS Modules。
- 检查：Ruff、pytest、ESLint、Prettier、TypeScript、Playwright Chromium。

Python 与 Node.js 版本分别见 `backend/.python-version`、`.node-version`，pnpm 版本见 `frontend/package.json`；依赖由各自锁文件固定。使用 mise 时可执行 `mise exec node@24.22.0 -- pnpm ...` 选择当前 Node.js 版本。

Python 实际链接的 SQLite 必须为 **3.51.3+**，这是本脚手架的完整性基线；检查与升级说明见[数据库指南](docs/database.md#sqlite-版本要求)。

运行入口依赖 POSIX sh，数据库文件锁使用 `fcntl`；当前没有原生 Windows 运行入口，实测平台与范围见[历史记录](docs/history.md)。

## 已有项目架构对齐

先盘点现状、建立验证基线与职责映射，再试迁一条业务链路并逐批推进。保留原项目的业务、数据和对外契约，分别评估数据库、配置来源和部署方式等技术选择。

[架构对齐指南](docs/project-alignment.md)给出差异表、迁移顺序和验收要求；具体执行计划与进度保存在原项目中。

## 基于脚手架创建新项目

macOS/Linux 上准备 uv 和 rsync，在模板根目录执行：

```bash
sh scripts/create-project.sh \
  --name my-app \
  --target-dir /absolute/path/to/my-app \
  --port 18002 \
  --vite-port 5174
```

目标必须是模板之外尚不存在的目录；创建器不安装依赖、建库或启动服务。参数、复制边界与后续步骤见[项目创建指南](docs/project-creation.md)。

## 配置文件

应用只读取显式 TOML，入口是 [configs/app.toml](configs/app.toml)。所有字段必填，拒绝未知项，不从环境变量、`.env`、旧 JSON 或代码默认值补齐；相对路径以项目根目录解析。

后端、Vite 与测试工具共用 Python 校验器。浏览器只接收 `client` 和应用标题/版本，前端配置变更需重新构建。字段、路径保护与 telemetry 环境隔离详见[配置约定](docs/configuration.md)。

## 首次运行

选择上述工具版本后，从项目根目录执行。以下建库步骤适用于新空库；已有数据库先按[数据库指南](docs/database.md)检查版本与备份要求。

```bash
uv sync --directory backend --frozen
pnpm --dir frontend install --frozen-lockfile
uv run --directory backend python -m entrypoints.cli db-check
uv run --directory backend python -m entrypoints.cli db-upgrade
pnpm --dir frontend build
sh backend/entrypoints/service.sh
```

随附配置访问 [http://127.0.0.1:18001/](http://127.0.0.1:18001/)。启动时检查数据库版本与前端产物，不自动迁移、安装依赖或构建。

| 路径                     | 用途                                  |
| ------------------------ | ------------------------------------- |
| `/`、`/welcome`          | Hello 欢迎页                          |
| `/api/v1/hello`          | Hello API                             |
| `/api/health`            | 服务和 SQLite 健康检查                |
| `/docs`、`/openapi.json` | API 文档和 Schema，开关及路径取自配置 |

## 服务控制

`sh backend/entrypoints/service.sh` 前台运行，Ctrl+C 停止，重新执行即可再次启动。信号与优雅关闭由 Uvicorn 处理，不提供后台控制子命令或 PID 管理，端口占用时只报错。

Shell 入口调用 `backend/entrypoints/service.py`（`python -m entrypoints.service`）装配并启动后端，应用工厂与资源生命周期仍由 `backend/app/application.py` 管理。

服务与维护命令必须使用同一配置；先准备包含全部字段的 `configs/app.local.toml`，再显式选择。CLI 的 `--config` 放在子命令前：

```bash
sh backend/entrypoints/service.sh --config configs/app.local.toml
# 维护前先在服务终端按 Ctrl+C 停止；此处只检查临时库
uv run --directory backend python -m entrypoints.cli --config configs/app.local.toml db-check
```

运行服务与数据库升级共用数据库旁的文件锁，运行期间不要删除锁文件。随附数据库为 `.data/app.sqlite3`，日志为 `logs/app.log`；Loguru 队列在退出时等待写完。自定义运行路径后检查 `.gitignore`，避免提交数据、备份、日志或私有配置。

## 可选 Vite 开发

先停止服务，将 `configs/app.toml` 中的 `serve_frontend` 设为 `false`，再分别在两个终端执行：

```bash
# 终端一
sh backend/entrypoints/service.sh
# 终端二
pnpm --dir frontend dev
```

随附配置访问 [http://127.0.0.1:5173/](http://127.0.0.1:5173/)。修改端口时同步 `vite.proxy_target` 与 `allowed_origins`；切回单服务模式时恢复 `serve_frontend = true`，重新构建并重启。

## 数据库与备份

升级、恢复或切换日常数据库前先停止服务，并确认其他数据库使用者也已停止。已有库需要升级前快照时，在新增或引入 revision **之前**，使用与旧库版本匹配的代码执行：

```bash
uv run --directory backend python -m entrypoints.cli db-backup
```

备份写入配置中的 `backup_directory`，校验后打印路径，不覆盖已有文件。不要只复制运行中的 SQLite 主文件，也不要删除活动的 WAL/SHM。完整备份、恢复及停服升级流程见[数据库指南](docs/database.md)。

### 迁移生成、审查与验证

模型变更与 Alembic revision 一同维护，已交付并执行过的迁移保持不变。候选迁移与临时库检查使用：

```bash
uv run --directory backend python -m entrypoints.cli db-revision -m "describe schema change"
uv run --directory backend python -m entrypoints.cli db-check
```

两者使用隔离临时库；`db-check` 不证明旧数据转换正确，也不检查日常库漂移。生成、审查、旧数据回归和显式应用的完整顺序见[迁移流程](docs/database.md#迁移生成审查与验证)。

## 接口类型与验证

命令从项目根目录执行，先安装前后端依赖。OpenAPI 导出不启动服务、不连接数据库；类型由生成器维护，检查模式不改写文件。

```bash
pnpm --dir frontend api:types
pnpm --dir frontend api:types:check
uv run --directory backend ruff check --config pyproject.toml . ../scripts/create_project.py
uv run --directory backend ruff format --check --config pyproject.toml . ../scripts/create_project.py
uv run --directory backend python -m entrypoints.cli db-check
uv run --directory backend pytest
pnpm --dir frontend format:check
pnpm --dir frontend lint
pnpm --dir frontend typecheck
pnpm --dir frontend build
```

按变更范围选择检查。Ruff 覆盖后端与项目创建器，`build` 包含 TypeScript 检查。格式整理使用对应的 `ruff format` 与 `pnpm --dir frontend format`，生成类型不交给 Prettier。

后端测试使用临时 TOML、日志和 SQLite；`integration` 测试需要本机监听与信号权限，受限环境可运行 `uv run --directory backend pytest -m 'not integration'`，但需另报未验证的真实启停。上面的 `build` 使用主 TOML 的输出位置；需要隔离验证构建时，使用下面的 E2E 入口，它也执行 TypeScript 检查与构建。

```bash
pnpm --dir frontend exec playwright install chromium
pnpm --dir frontend test:e2e
```

E2E 统一经 `test:e2e` 创建临时构建、数据库、日志和独立服务，不复用日常数据与产物。可加 `--config /absolute/path/app.test.toml` 提供完整测试设置；成功且 `testing.keep_artifacts = false` 时清理，设为 true 或失败时保留并打印产物位置。不要直接执行 Playwright test 绕过隔离入口；Chromium 的本机进程权限不足时报告验证限制。

## 替换 Hello 示例

后端从 `routers/hello.py`、`services/hello.py`、`schemas/hello.py` 入手，前端从 `pages/WelcomePage.tsx` 与 `components/ConnectionStatus.tsx` 入手。按[当前设计](docs/design.md#后端职责与数据库)划分业务类、依赖工厂与响应映射；新增持久化模型时同步迁移、生成类型和测试，并按业务调整各级 `AGENTS.md`。
