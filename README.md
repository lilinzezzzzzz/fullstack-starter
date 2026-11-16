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
| 服务与维护入口     | [entrypoints/service.sh](entrypoints/service.sh) 提供服务 Shell 入口；[backend/entrypoints/](backend/entrypoints/) 保留服务 Python 实现及配置/OpenAPI、数据库维护 CLI                      |
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
sh entrypoints/service.sh run
```

随附配置访问 [http://127.0.0.1:18001/](http://127.0.0.1:18001/)。启动时检查数据库版本与前端产物，不自动迁移、安装依赖或构建。

| 路径                               | 用途                                  |
| ---------------------------------- | ------------------------------------- |
| `/`、`/welcome`                    | Hello 欢迎页                          |
| `/api/v1/hello`                    | Hello API                             |
| `/api/health`                      | 服务和 SQLite 健康检查                |
| `/docs`、`/redoc`、`/openapi.json` | API 文档和 Schema，开关及路径取自配置 |

## 服务控制

唯一服务 Shell 入口是根目录 `entrypoints/service.sh`，Python 实现保留在 `backend/entrypoints/`，不保留旧 Shell 入口。脚本从自身位置定位项目，通过 uv 查询预装解释器后直接 exec Python；支持项目外工作目录和带空格路径，不安装依赖、迁移数据库或构建前端。

| 命令      | 行为                                                                                                   |
| --------- | ------------------------------------------------------------------------------------------------------ |
| `start`   | 操作锁内先查实例；已有实例提示并返回 0，不读取本次配置，否则加载配置并后台启动，等待实例就绪与健康检查 |
| `run`     | 操作锁内先查实例；已有实例提示并返回 0，不读取本次配置，否则加载配置并前台运行                         |
| `status`  | 仅用实例状态与认证控制通道查询实际阶段和健康，不加载 TOML                                              |
| `stop`    | 仅用实例状态认证目标，由目标进程自行触发 SIGINT；等待资源、日志及实例锁清理，不加载 TOML               |
| `restart` | 锁内读取、校验并冻结目标配置，停止当前实例后按同一快照后台启动；允许切换配置路径                       |

```bash
sh entrypoints/service.sh start
sh entrypoints/service.sh status
sh entrypoints/service.sh restart --config configs/app.local.toml
sh entrypoints/service.sh stop
sh entrypoints/service.sh run
```

必须显式指定子命令。新实例默认使用项目根目录的 `configs/app.toml`；`start/run` 已有实例时忽略 `--config`，即使目标文件缺失或损坏也只展示当前实例。`status/stop` 始终忽略 `--config`，原配置改动、损坏或删除都不影响管理当前实例。切换配置使用 `restart --config ...`；不传参数的 `restart` 固定使用 `configs/app.toml`，不沿用旧实例配置。

`restart` 等待命令锁期间不提前读取配置；锁内读取失败时保留当前实例。校验后的原文件再变化，也不改变本次启动：父进程通过匿名文件描述符传递原始 TOML 快照，子进程只校验这份文档，不重新打开原文件。配置快照保留完整字段及业务连接令牌，仅经匿名描述符传递，不写入具名文件、命令行或日志；公开配置导出仍执行各字段原有掩码规则。

每个项目只有一个实例，所有配置共用根目录 `.run/`：

```text
.run/
├── instance.json   # 协议版本、实例身份、认证凭据、实际地址、日志和停止期限；0600
├── run.lock        # 覆盖完整运行、资源关闭及末尾日志清理
├── control.lock    # 命令串行执行，最长等待 40 秒
└── console.log     # 后台输出和启动诊断
```

`.run/` 和运行文件拒绝符号链接重定向，运行文件仅供当前用户访问；这些检查不依赖 TOML，因此 `status/stop` 也不能绕过。控制通道的随机令牌仅保存在 0600 的 `instance.json` 及原子更新期间同权限的 `instance.json.pending` 中，不进入配置快照、控制台、应用日志、命令行或 Git。实例记录中的 `command` 是不含内部 `--settings-fd` 的规范化公开启动命令，不代表冻结配置内容的重放。实例记录以 `instance.json.pending` 原子替换。所有命令需要可写的 `.run/` 来取得串行锁。运行锁已被持有但身份尚未登记时，`start/run` 提示登记中并返回 0，不创建第二个实例；`status` 返回 starting/1，`stop` 因无法认证目标返回 1，不发送信号。这些结果不表示实例已经健康就绪。运行锁已释放的遗留记录不作为存活证据，`status/stop` 报已停止；下一次后台 `start/restart` 或前台 `run` 登记新实例时替换遗留记录。运行期间不删除锁文件；目录和协议不按配置路径、数据库或端口划分。实例协议升级前先用原版本停止实例，活跃的未知或旧格式记录会拒绝控制，不按 PID 猜测或接管。

成功返回 0；`status` 健康为 0，已停止为 3，未就绪、不健康、控制不可达或错误为 1；非法参数为 2。五个命令被 Ctrl+C 中断均返回标准 SIGINT 退出码 130，前台 `run` 仍先优雅停服；SIGTERM 同样完成资源、日志和实例清理后返回 143；重复 `stop` 对未运行实例返回 0。

启动与停止期限显式取 `[service]`，停止期限必须大于 `server.graceful_shutdown_seconds`；停止现有实例使用其启动时保存的期限。HTTP 健康探测默认等待 1 秒，后台启动探测还受剩余启动期限限制；控制连接的 0.5 秒预算保持独立。停止失败不继续重启，启动失败只回收本次创建的子进程，超时保留实例并报错，不自动 SIGKILL。不按占用端口或记录 PID 向外部进程发信号。

数据库仍使用 `.data/app.sqlite3`，应用日志仍按 `[logging]` 写入。服务和维护 CLI 操作同一数据库时使用同一完整配置；维护前先停服，数据库旁操作锁与实例锁职责不同，不要删除活动 WAL/SHM。其他信号及强制终止的边界见[进程约定](docs/design.md#配置访问与进程边界)。

## 可选 Vite 开发

先停止服务，将 `configs/app.toml` 中的 `serve_frontend` 设为 `false`，再分别在两个终端执行：

```bash
# 终端一
sh entrypoints/service.sh run
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

E2E 统一经 `test:e2e` 执行 TypeScript 检查、临时生产构建、数据库升级和浏览器流程，随附配置使用 Chromium；通过临时后端项目副本的 Shell 入口启动独立服务，隔离固定 `.run/`，不复用日常数据与产物。正常收尾使用 SIGINT，沿用 Uvicorn 原生 Ctrl+C 关闭路径并等待日志写完。后端服务 fixture 在失败时也尝试认证停服，辅助器超时发 SIGINT，超过停止期限则失败并保留诊断，不发 SIGKILL。E2E 运行器仅对自己创建的临时进程保留最终 SIGKILL 回收例外，命令超时仍必须失败，不能据此证明优雅关闭成功。

可加 `--config /absolute/path/app.test.toml` 提供完整测试设置；成功且 `testing.keep_artifacts = false` 时清理，设为 true 或失败时保留并打印产物位置。不要直接执行 Playwright test 绕过隔离入口；Chromium 的本机进程权限不足时报告验证限制。

## 替换 Hello 示例

后端示例位于 `backend/app/` 下的 `routers/hello.py`、`services/hello.py`、`schemas/hello.py`，前端示例位于 `frontend/src/` 下的 `pages/WelcomePage.tsx` 与 `components/ConnectionStatus.tsx`。按[当前设计](docs/design.md#后端职责与数据库)划分业务类、依赖工厂与响应映射；在 `backend/app/application.py` 注册业务路由，新增持久化模型时同步迁移、生成类型和测试，并按业务调整各级 `AGENTS.md`。
