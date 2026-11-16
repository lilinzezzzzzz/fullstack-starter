# fullstack-starter

面向本地、单用户、单机应用的 FastAPI + SQLite + React 脚手架。默认由单 worker FastAPI 提供页面和 API；V1 只有 Hello 欢迎页、Hello API 与数据库健康检查，不创建业务表。

| 需要做什么           | 入口                                              |
| -------------------- | ------------------------------------------------- |
| 安装并运行           | [首次运行](#首次运行)                             |
| 创建独立的新项目     | [项目创建指南](docs/project-creation.md)          |
| 对齐正在开发的项目   | [已有项目架构对齐指南](docs/project-alignment.md) |
| 了解目录、分层与契约 | [代码入口](#代码入口)、[当前设计](docs/design.md) |
| 修改配置             | [配置约定](docs/configuration.md)                 |
| 备份、恢复或编写迁移 | [数据库维护与迁移](docs/database.md)              |
| 查看历史实测结果     | [实现与验证记录](docs/history.md)                 |

## 技术栈

- 后端：Python、uv、FastAPI、Pydantic v2、SQLAlchemy 2.0 async、aiosqlite、SQLite、Alembic、Loguru。
- 前端：Node.js、pnpm、React、TypeScript、Vite、React Router、TanStack Query、Ant Design、CSS Modules。
- 检查：Ruff、pytest、ESLint、Prettier、TypeScript、Playwright Chromium。

Python 与 Node.js 版本分别见 `backend/.python-version`、`.node-version`，pnpm 版本见 `frontend/package.json`；依赖由各自锁文件固定。已有 mise 和 Corepack 时，可用 `mise exec node@24.22.0 -- corepack pnpm@9.12.2 --dir frontend ...` 显式选择随附版本；调整工具版本后同步核对上述声明。

Python 实际链接的 SQLite 必须为 **3.51.3+**，这是本脚手架的完整性基线；检查与升级说明见[数据库指南](docs/database.md#sqlite-版本要求)。

运行入口依赖 POSIX sh，数据库文件锁使用 `fcntl`；当前没有原生 Windows 运行入口，实测平台与范围见[历史记录](docs/history.md)。

## 代码入口

| 职责               | 位置与边界                                                                                                                                                                                 |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 服务与维护入口     | [backend/entrypoints/](backend/entrypoints/)：`service.sh` 调用 `service.py` 提供前台运行与后台启停；`cli.py` 提供配置/OpenAPI 导出和数据库维护命令                                        |
| 应用装配           | [backend/app/application.py](backend/app/application.py)：`create_app(settings)` 显式接收配置，组织中间件、异常处理、路由、OpenAPI 和前端挂载；同文件 lifespan 管理运行资源                |
| 基础设施与底层工具 | [infra/](backend/app/infra/) 提供数据库、日志、静态托管与通用 HTTP 适配；[utils/](backend/app/utils/) 仅放标准库路径策略和数据库锁                                                         |
| HTTP 与业务        | [routers/](backend/app/routers/)、[services/](backend/app/services/)、[schemas/](backend/app/schemas/) 分别承担请求适配、业务规则与接口结构；持久化结构放在 [models/](backend/app/models/) |
| 浏览器与工程工具   | [frontend/src/](frontend/src/) 组织页面、请求和查询；[scripts/](scripts/) 提供独立项目创建器                                                                                               |

依赖方向、资源关闭顺序和固定契约以[当前设计](docs/design.md)及各目录 `AGENTS.md` 为准。

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

字段用途、单位、可选值和零值含义见 TOML 注释，定义与校验在 [backend/app/config.py](backend/app/config.py)。固定日志类属性和派生属性不属于 TOML 字段，不能通过添加同名键修改。

后端、Vite 与测试工具共用 Python 校验器。浏览器只接收 `client` 和应用标题/版本，前端配置变更需重新构建。配置来源、路径保护与 telemetry 环境隔离详见[配置约定](docs/configuration.md)。

## 首次运行

选择上述工具版本后，从项目根目录执行。以下建库步骤适用于新空库；已有数据库先按[数据库指南](docs/database.md)检查版本与备份要求。

```bash
uv sync --directory backend --frozen
pnpm --dir frontend install --frozen-lockfile
uv run --directory backend python -m entrypoints.cli db-check
uv run --directory backend python -m entrypoints.cli db-upgrade
pnpm --dir frontend build
sh backend/entrypoints/service.sh run
```

随附配置访问 [http://127.0.0.1:18001/](http://127.0.0.1:18001/)。启动时检查数据库版本与前端产物，不自动迁移、安装依赖或构建。

| 路径                               | 用途                                  |
| ---------------------------------- | ------------------------------------- |
| `/`、`/welcome`                    | Hello 欢迎页                          |
| `/api/v1/hello`                    | Hello API                             |
| `/api/health`                      | 服务和 SQLite 健康检查                |
| `/docs`、`/redoc`、`/openapi.json` | API 文档和 Schema，开关及路径取自配置 |

## 服务控制

入口必须指定子命令；不指定 `--config` 时固定读取项目根目录的 `configs/app.toml`，不根据当前工作目录查找配置。

| 命令      | 行为                                                                                |
| --------- | ----------------------------------------------------------------------------------- |
| `run`     | 前台运行，Ctrl+C 优雅停止；用于调试与 E2E                                           |
| `start`   | 后台启动，Uvicorn 启动且 `/api/health` 正常后返回 PID、地址及日志位置               |
| `status`  | 显示 healthy、unhealthy、starting、stopping、unreachable、config-changed 或 stopped |
| `stop`    | 认证目标实例，由目标进程自行触发 SIGINT，等待资源与日志清理                         |
| `restart` | 先停止再后台启动；停止失败时不启动                                                  |

```bash
sh backend/entrypoints/service.sh start
sh backend/entrypoints/service.sh status
sh backend/entrypoints/service.sh restart
sh backend/entrypoints/service.sh stop
```

重复 `start` 对健康且配置一致的实例返回成功；重复 `stop` 对未运行实例返回成功。`status` 的退出码为健康 0、已停止 3、其他状态或错误 1；缺少或非法子命令返回 2。其他命令成功为 0，执行失败为 1。`run` 遇到原生信号时沿用 Uvicorn/Python 的退出行为。

启动和停止等待期限取 `[service]`。启动失败会回收本次创建的子进程；清理或停止超时保留实例并报错，不自动 SIGKILL。端口占用只报错，不处理占用端口的进程。不自动安装依赖、迁移数据库或构建前端。

服务与维护命令必须使用同一配置；先准备包含全部字段的 `configs/app.local.toml`，再显式选择。CLI 的 `--config` 放在子命令前：

```bash
sh backend/entrypoints/service.sh start --config configs/app.local.toml
# 使用同一配置停止服务；此处 db-check 只检查临时库
sh backend/entrypoints/service.sh stop --config configs/app.local.toml
uv run --directory backend python -m entrypoints.cli --config configs/app.local.toml db-check
```

每个项目只允许一个服务实例。所有配置共用项目根目录的 `.run/`，更换数据库、端口或 `--config` 不能并行启动另一个实例；管理现有实例时使用其启动配置路径。

```text
.run/
├── instance.json   # PID、UTC 启动时间、完整 Python 命令、配置路径和控制身份
├── run.lock        # 服务运行及清理期间持有
├── control.lock    # 串行执行启停命令
└── console.log     # 后台标准输出、错误及启动诊断
```

实例记录通过临时 `instance.json.pending` 原子替换，权限为 0600，不得提交或分享。正常退出删除记录，两个锁文件保留；是否运行取决于锁是否被持有。`.run/` 固定在项目根目录，不由 TOML 或环境变量另选，也不允许符号链接重定向。配置内容更新后使用 `restart`；更换配置文件路径前先停止旧实例。

数据库继续位于 `.data/app.sqlite3`，应用日志位于 `logs/app.log`，两者仍按 TOML 配置。运行服务与数据库升级共用数据库旁的 `.data/app.sqlite3.lock`，它用于数据库维护互斥，与 `.run/run.lock` 职责不同；运行期间不要删除锁文件。前台 Ctrl+C 和 `stop` 均等待资源清理与 Loguru 队列写完。其他信号和强制终止的日志边界见[进程约定](docs/design.md#配置访问与进程边界)。自定义运行路径后检查 `.gitignore`，避免提交数据、备份、日志或私有配置。

## 可选 Vite 开发

先停止服务，将 `configs/app.toml` 中的 `serve_frontend` 设为 `false`，再分别在两个终端执行：

```bash
# 终端一
sh backend/entrypoints/service.sh run
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

按变更范围选择检查。Ruff 覆盖后端与项目创建器，`build` 包含 TypeScript 检查；Python 格式整理使用 `ruff format`，接口类型通过生成器维护。

`pnpm --dir frontend format:check` 统一检查前端文件、根 README、`docs/` 下全部 Markdown 和各级 `AGENTS.md`，新增子目录自动纳入；`pnpm --dir frontend format` 整理相同范围。两者共用根 `.prettierrc.toml`，并读取根 `.prettierignore` 和 `.gitignore`，排除生成类型、锁文件、依赖、构建和私有运行产物。

后端服务测试使用独立临时项目副本，隔离项目 `.run/`，其余测试使用临时 TOML、日志和 SQLite；`integration` 测试需要本机监听与信号权限，受限环境可运行 `uv run --directory backend pytest -m 'not integration'`，但需另报未验证的真实启停。上面的 `build` 使用主 TOML 的输出位置；需要隔离验证构建时，使用下面的 E2E 入口，它也执行 TypeScript 检查与构建。

```bash
pnpm --dir frontend exec playwright install chromium
pnpm --dir frontend test:e2e
```

E2E 统一经 `test:e2e` 执行 TypeScript 检查、临时生产构建、数据库升级和浏览器流程，随附配置使用 Chromium；通过临时后端项目副本的 Shell 入口启动独立服务，隔离固定 `.run/`，不复用日常数据与产物。正常收尾使用 SIGINT，沿用 Uvicorn 原生 Ctrl+C 关闭路径并等待日志写完。

可加 `--config /absolute/path/app.test.toml` 提供完整测试设置；成功且 `testing.keep_artifacts = false` 时清理，设为 true 或失败时保留并打印产物位置。不要直接执行 Playwright test 绕过隔离入口；Chromium 的本机进程权限不足时报告验证限制。

## 替换 Hello 示例

后端示例位于 `backend/app/` 下的 `routers/hello.py`、`services/hello.py`、`schemas/hello.py`，前端示例位于 `frontend/src/` 下的 `pages/WelcomePage.tsx` 与 `components/ConnectionStatus.tsx`。按[当前设计](docs/design.md#后端职责与数据库)划分业务类、依赖工厂与响应映射；在 `backend/app/application.py` 注册业务路由，新增持久化模型时同步迁移、生成类型和测试，并按业务调整各级 `AGENTS.md`。
