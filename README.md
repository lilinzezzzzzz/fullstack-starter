# fullstack-starter

一个面向本地工具和单机应用的小型全栈脚手架。前后端同仓库，默认由单 worker FastAPI 提供页面和 API。

V1 只有 Hello 欢迎页、Hello API 和 SQLite 健康检查。后端按 `routers / services / models / schemas` 分层，不创建业务表。

| 文档 | 内容 |
| --- | --- |
| [README](README.md) | 安装、运行、开发和数据维护 |
| [设计方案](docs/design.md) | 当前技术选型、目录、职责和 V1 范围 |
| [配置约定](docs/configuration.md) | 全部必填字段、配置流和固定契约边界 |
| [实现与验证记录](docs/history.md) | 历史变更、验证结果及其适用范围 |

## 技术栈

- Python 3.14.7、uv；FastAPI、Pydantic v2、异步 SQLAlchemy 2.0、aiosqlite、SQLite、Alembic、Loguru。
- Node.js 24.22.0 LTS、pnpm 9.12.2；React、TypeScript、Vite、React Router、TanStack Query、Ant Design、CSS Modules。
- Ruff、pytest、ESLint、Prettier、TypeScript、Playwright Chromium。

解释器版本见 `backend/.python-version` 和 `.node-version`。依赖由两份锁文件固定。SQLite 实际库版本至少为 3.51.3，本地验证版本为 3.53.1。使用 mise 时，可以通过 `mise exec node@24.22.0 -- pnpm ...` 选择正确的前端工具版本。

SQLite 下限是数据完整性基线：3.51.3 修复了多个连接写入/checkpoint 时可能触发的 [WAL-reset 数据损坏问题](https://sqlite.org/wal.html#walresetbug)，并非 WAL 功能的首次支持版本。本脚手架对 WAL 和 DELETE 统一使用这条基线，不按发行版的回补补丁放宽版本号。

检查 Python 实际链接的 SQLite，而非系统 `sqlite3` 命令的版本：

```bash
uv run --directory backend python -c 'import sqlite3; print(sqlite3.sqlite_version)'
```

版本不足时，安装链接到 SQLite 3.51.3+ 的 Python 3.14 构建，再用 uv 重建后端虚拟环境；仅更新 SQLite 命令行程序不会改变 Python 链接的库。

## 基于脚手架创建新项目

### 1. 用脚本生成

在 macOS/Linux 上准备 uv 和 rsync。脚本使用 `backend/.python-version` 固定的 Python 标准库，创建阶段不要求先安装应用依赖；Python 尚未安装时由 uv 准备。

在脚手架根目录执行：

```bash
sh scripts/create-project.sh \
  --name my-app \
  --target-dir /absolute/path/to/my-app \
  --port 18002 \
  --vite-port 5174
```

也可以从其他工作目录使用脚本的绝对路径调用。`--target-dir` 是新项目的最终目录，不会再自动追加项目名；相对路径以调用时的工作目录解析。目录名可以与项目标识不同，含空格时加引号。

| 参数 | 要求与含义 |
| --- | --- |
| `--name` | 必填；1–63 位小写英文字母、数字和连字符，以字母开头，连字符不能连续或位于末尾 |
| `--target-dir` | 必填；最终目标目录，必须尚不存在且位于脚手架目录之外，缺失的父目录会创建 |
| `--port` | 必填；新项目后端端口，范围 1–65535 |
| `--vite-port` | 可选；省略时继承模板 `configs/app.toml` 的 `vite.port`，必须与后端端口不同 |
| `--help` | 查看参数说明 |

脚本校验参数和目标目录；端口是否已被占用在服务实际启动时检查，不预留端口或处理占用端口的进程。

### 2. 自动完成的调整

- 复制源码、迁移、规则、文档、生成类型和两份锁文件；依据 `.gitignore` 排除数据、备份、日志、PID、依赖、缓存、构建产物和本地配置，并排除 `.git`、`.env*` 与 `.secrets*`。
- 额外排除 TOML 指定的实际运行路径，并将新项目的运行路径补入副本 `.gitignore`，支持模板内的自定义目录。数据、备份、日志、PID 和前端输出路径必须在模板目录内；内部绝对路径会改为相对路径，避免指向原项目。模板外的这些路径会明确报错，需先调整模板配置。
- 复制前复用应用的源码路径保护规则，并校验创建所需的关键字段；复制后按源文件树检查 API、路由、服务、迁移、sh 脚本、前端入口和项目元信息；缺少文件时创建失败，不报告成功。
- 将后端项目名改为 `my-app-backend`，前端包名改为 `my-app-frontend`，应用标题改为 `my-app`，PID 文件改为原 PID 目录下的 `my-app.pid`。
- 同步后端端口、Vite 端口、代理目标和允许来源。其余应用配置完整继承模板，保留 TOML 注释，不读取环境变量或补齐缺失配置。
- 只更新 `uv.lock` 中本地虚拟项目的名称，并用 `uv lock --check --offline` 校验；第三方依赖版本、哈希和前端锁文件保持不变，创建时无需重新解析依赖源。
- 更新新项目 README、设计文档中的项目名称和端口，为继承的验证记录注明来源。示例测试按应用标题和 Vite 配置断言，重命名后可直接运行。

目标目录已存在（包括文件或符号链接）时直接拒绝覆盖；复制或配置调整失败时，清理本次新建的目标目录。sh 入口调用 [scripts/create_project.py](scripts/create_project.py) 处理结构化数据，仅依赖 Python 标准库和 rsync。

创建器校验路径、源文件完整性，以及创建过程依赖的关键字段。由于它不引入应用依赖，完整 Pydantic 字段、枚举和跨字段校验由生成项目的 `export-settings`、测试或首次启动完成；创建器不会把明显无效的模板配置包装成成功项目。

创建完成后会打印后续命令。新项目从空数据库开始，依赖、建库、构建、Git 和服务由下面的步骤分别准备；原项目的数据与服务不受创建操作影响。

### 3. 安装、验证与运行

以下以 `my-app`、后端 `18002` 和 Vite `5174` 为例。先选择“技术栈”中固定的 Node.js、pnpm 版本，再进入新目录：

```bash
cd /absolute/path/to/my-app
uv sync --directory backend --frozen
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend api:types
uv run --directory backend pytest
pnpm --dir frontend format:check
pnpm --dir frontend lint
pnpm --dir frontend api:types:check
pnpm --dir frontend build
uv run --directory backend python -m app.cli db-upgrade
sh scripts/service.sh start
sh scripts/service.sh status
```

`build` 包含 TypeScript 检查。完整静态检查与 Chromium 页面流程见下方“接口类型与验证”；后端测试使用临时数据库，不依赖新项目的日常库。

访问 [新项目欢迎页](http://127.0.0.1:18002/)，确认连接成功；[Hello API](http://127.0.0.1:18002/api/v1/hello) 应返回 `Hello, my-app!`，[健康检查](http://127.0.0.1:18002/api/health) 应显示数据库正常。运行路径以新项目自己的 TOML 为准。

查看完成后停止服务，正常停止会清理 `.run/my-app.pid`，`.run/my-app.pid.lock` 可以保留：

```bash
sh scripts/service.sh stop
```

需要 Vite 热更新时，按下方“可选 Vite 开发”设置 `serve_frontend = false`，本例访问 `http://127.0.0.1:5174/`。其他章节仍以脚手架随附设置为例，实际端口以新项目 TOML 为准。

### 4. 建立版本库并开始业务开发

需要独立版本管理时，在新项目根目录执行：

```bash
git init
git status --short --untracked-files=all
```

先检查待跟踪文件，再进行首次提交。新项目维护自己的 Git 历史和锁文件；复制后的代码与脚手架独立，后续升级需选择性迁移并重新验证。

新项目仍以 Hello 页面起步。按实际业务更新 README、设计文档和 AGENTS 约束，再按下方“替换 Hello 示例”增加业务代码、Alembic 迁移、接口类型与测试。继承的历史验证只代表模板，新项目自己的验证结果另行记录。

## 配置文件

应用配置为 [configs/app.toml](configs/app.toml)。TOML 支持注释和分组，适合这套人工维护的 Python 项目。Python 原生解析并统一校验全部 86 个叶子配置项，Vite 和测试工具复用校验结果。

**所有配置字段必填，没有代码默认值、环境变量、`.env`、隐式合并或旧 JSON 回退。** 缺文件、缺字段、未知项、错误类型和无效数值均明确失败。`0`、`false` 和空列表是显式值，不会被替换成其他值。具体单位与取值见 TOML 注释。

| 分组 | 主要内容 |
| --- | --- |
| 根配置 | 数据/备份/前端路径、数据库文件名、前端托管、本机访问边界 |
| `application` | 标题、版本、文档开关和路径 |
| `server` | 地址、端口、单 worker、Keep-Alive、backlog、并发上限和关闭预算 |
| `database` | SQLite 日志模式、持久化级别和连接池参数 |
| `logging` | 文件、格式、等级、轮转、保留、压缩、序列化和请求日志 |
| `service` | PID 文件、启停/检查超时和轮询间隔 |
| `vite` | 开发地址、端口、代理和严格端口策略 |
| `client` | 请求超时、缓存、重试、刷新策略和组件主题 |
| `testing` | 临时目录、进程预算、浏览器、视口、重试和超时 |

相对路径一律以项目根目录为基准，也支持绝对路径。配置文件选址是固定引导约定，和字段默认值不同；另选文件可传 `--config`。接口路径、PID 身份检查、事务完整性等固定契约保留在代码中，详见配置审查文档。

运行目录不得与源码、配置、文档或 `.git` 重叠；前端仅允许 `frontend/dist` 子树作为 `frontend/` 内的输出位置。路径检查会解析符号链接、折叠大小写，并检查目录包含关系的两个方向；通过符号链接把 `frontend/dist` 指向外部时不允许自动清空。除源码外，遗留 `data/`、`.data/`、`logs/`、`.run/`、`.venv/`、`node_modules/` 和 Python 缓存目录也受保护；数据库、应用日志、bootstrap log 和 PID 不得指向同一文件。

FastAPI 原生 OpenTelemetry 在代码中显式关闭；环境变量和已有全局 provider 不会启用该功能。Loguru 应用、请求和 Uvicorn 日志仍按 TOML 工作。需要遥测的业务项目再显式引入配置、依赖和数据处理规则。

前端构建需要后端依赖，以便使用同一校验器。仅 `client` 和应用标题/版本注入浏览器；服务端路径和完整配置不会打包。后端改配置后重启，前端参数改动后重新构建。外部工具的 PATH、缓存和测试浏览器位置不作为应用参数来源。

随文件提供的运行设置为 18001 端口、根目录 `.data/app.sqlite3`、`logs/app.log` 和 `.run/fullstack-starter.pid`。保留日志设置为 `retention_days = 0`，表示不自动删除历史日志，不是缺项时的默认策略。

修改 PID 路径前先停服务。启停使用启动时同一个配置文件路径。

## 首次运行

以下命令从项目根目录执行：

```bash
uv sync --directory backend --frozen
pnpm --dir frontend install --frozen-lockfile
uv run --directory backend python -m app.cli db-upgrade
pnpm --dir frontend build
sh scripts/service.sh start
```

打开 [http://127.0.0.1:18001/](http://127.0.0.1:18001/)。后端检查数据库版本及前端产物，启动时不自动迁移、安装依赖或构建。

| 路径 | 用途 |
| --- | --- |
| `/`、`/welcome` | Hello 欢迎页 |
| `/api/v1/hello` | Hello API |
| `/api/health` | 服务和 SQLite 健康检查 |
| `/docs`、`/openapi.json` | API 文档和 Schema |

## 服务控制

```bash
sh scripts/service.sh start
sh scripts/service.sh status
sh scripts/service.sh restart
sh scripts/service.sh stop
```

脚本只管理后端服务，内部用 Python 标准库处理 TOML、进程与信号，不依赖 jq、PM2 或 systemd。脚本从其他目录调用时也能定位项目。

服务控制实现在 [backend/tools/service_control.py](backend/tools/service_control.py)，sh 入口在后端环境中以 `python -m tools.service_control` 调用它。工具复用 `app` 的配置、日志和应用工厂，`app` 不反向导入工具代码。项目创建器放在根目录 `scripts/`，后端进程工具放在 `backend/tools/`。

PID 默认保存在 `.run/fullstack-starter.pid`，操作锁自动派生为 `.run/fullstack-starter.pid.lock`，无需额外配置。启停或维护操作会创建父目录，`.run/` 整体被 Git 忽略，生成项目不复制其中的运行状态。更改 PID 路径前，先用旧配置停止服务并确认没有启停或迁移操作在进行，再切换配置和处理旧锁文件。

- 真正监听成功后才记录实际服务 PID；重复启动返回当前 PID。
- 发送 SIGTERM 前核对 PID 对应的模块和配置路径，不按端口批量杀进程。
- 正常停止后删除 PID 文件；已停止时再次停止也能成功。
- 陈旧的已退出 PID 会在启动或停止时清理；指向其他程序的 PID 和非法文件不会被覆盖或用于发信号。
- 停止超时保留 PID，不自动发送 SIGKILL。
- `.pid.lock` 是控制操作的互斥锁文件，停止后可以保留，操作结束时内核锁已释放。
- `status` 的退出码为 0（运行中）、3（已停止）或 1（检查失败）。

默认日志保存在根目录 `logs/app.log`，由 Loguru 统一记录应用、请求标识和 Uvicorn 日志；`logs/service.log` 捕获导入或启动早期错误。诊断日志不打印局部变量。随附运行目录、常见日志、PID、SQLite 文件及 WAL/SHM 辅助文件均被 Git 忽略；`.env*`、`.secrets*` 也保持忽略。

直接修改模板或已有项目的运行路径时，应同步维护 `.gitignore`。生成器只会自动补充新副本的规则。使用 `git check-ignore --no-index <实际产物路径>` 核对，并在提交前检查 `git status --short --untracked-files=all`。

后端维护和服务命令支持显式选择其他完整配置文件：

```bash
sh scripts/service.sh start --config configs/app.local.toml
sh scripts/service.sh stop --config configs/app.local.toml
uv run --directory backend python -m app.cli --config configs/app.local.toml db-upgrade
```

`configs/*.local.toml` 被 Git 忽略；旧的私有 JSON 仍保持忽略但不会读取。Vite 常规构建与开发使用主 TOML；测试会生成完整的临时 TOML。

## 可选 Vite 开发

在 `configs/app.toml` 中将 `serve_frontend` 改为 `false`，再执行：

```bash
sh scripts/service.sh restart
pnpm --dir frontend dev
```

访问 [http://127.0.0.1:5173/](http://127.0.0.1:5173/)。Vite 的地址、端口和代理目标也来自配置文件。调整后端端口时同步 `vite.proxy_target`，调整 Vite 来源时同步 `allowed_origins`。

切回单服务模式时，将 `serve_frontend` 改回 `true`，重新构建前端并重启服务。前端构建目录来自 `frontend_dir`；自定义输出目录不会被构建工具自动清空。

## 数据库与备份

随附配置的数据库位于项目根目录的 `.data/app.sqlite3`，备份目录为 `.data/backups/`；连接开启 WAL、外键、保守持久化设置和有限锁等待。初始迁移只有 `alembic_version`，没有业务表。`.data/` 是运行数据目录，保持 Git 忽略。

升级已有数据库前先停止服务，审查迁移并按需备份；完成后再启动。`db-upgrade` 与启停共用互斥锁，有 PID 文件时拒绝迁移；陈旧或异常 PID 也不会被迁移命令删除，应通过同配置的 `service.sh stop` 核查处理。该保护针对脚本管理的服务，直接启动的 Uvicorn 或其他使用同一数据库的程序也必须先停止。

```bash
sh scripts/service.sh stop
uv run --directory backend python -m app.cli db-upgrade
sh scripts/service.sh start
uv run --directory backend python -m app.cli db-backup
```

维护命令与服务必须使用同一个配置文件。备份通过 SQLite Backup API 创建一致性快照，校验完整性与版本后打印路径，保存到 `backup_directory` 指定的位置，不覆盖旧文件。

恢复时先停止服务并按需备份当前数据库。校验候选快照完整性、版本和记录后，复制到新的数据目录，文件名与 `database_filename` 一致；修改配置文件的 `data_dir` 指向副本，审查并执行必要迁移后再启动。保留原库，确认恢复成功后再处理旧文件。

不要在应用运行时只复制主数据库作为备份，也不要手工删除活动的 WAL/SHM 文件。

## 异步数据库调用约定

数据库使用 `sqlite+aiosqlite` 和 `AsyncEngine`。应用生命周期中创建 `async_sessionmaker`，每个请求通过异步依赖获得独立的 `AsyncSession`，关闭应用时 `await engine.dispose()`。

含数据库 I/O 的 Router、Service 和 DAO 使用 `async def`，通过 `await session.execute()`、`await session.flush()` 等访问数据库。写入事务由 Service 使用 `async with session.begin()` 管理，成功提交、失败回滚。纯计算的 Hello Service 可以继续使用普通函数。

不要跨并发任务共享 AsyncSession，也不要将未加载的 ORM 关系交给响应序列化触发隐式 I/O。SQLite 连接使用 SQLAlchemy 官方事件方式显式发出 BEGIN，保留外键、WAL 和事务完整性。

Alembic 的命令入口仍是维护 CLI：迁移环境创建异步引擎，通过 `AsyncConnection.run_sync()` 将 Alembic 的同步 DDL API 桥接到异步驱动；不要在应用请求内自动升级数据库。同步测试准备可以调用 `upgrade_database()`，异步测试通过线程边界调用该同步维护入口。

备份实现在 `backend/app/services/backup.py`，使用 aiosqlite 的异步 Backup API；CLI 负责参数和事件循环。取消时等待已经提交的复制完成再关闭目标连接、删除未返回的快照，并继续传播取消，不重新发起复制。

`database.synchronous` 是 SQLite 的持久化级别，与 SQLAlchemy 的同步/异步调用方式无关。异步驱动使用相同的 SQLite 文件格式，不需要另建数据库或切换迁移版本。

## 接口类型与验证

OpenAPI 导出不启动服务，也不连接数据库或创建日志目录：

```bash
pnpm --dir frontend api:types
pnpm --dir frontend api:types:check
```

生成类型随 API 变更提交，检查模式失败时不改写生成文件。

```bash
uv run --directory backend ruff check --config pyproject.toml . ../scripts/create_project.py
uv run --directory backend ruff format --check --config pyproject.toml . ../scripts/create_project.py
uv run --directory backend pytest
pnpm --dir frontend format:check
pnpm --dir frontend lint
pnpm --dir frontend typecheck
pnpm --dir frontend build
```

Python 检查统一使用 `backend/pyproject.toml`，覆盖后端和根目录的项目创建器。格式整理使用 `uv run --directory backend ruff format --config pyproject.toml . ../scripts/create_project.py` 和 `pnpm --dir frontend format`。编辑器基础约定见根目录 `.editorconfig`，前端格式规则见 `frontend/.prettierrc.toml`。自动生成的 API 类型交给生成器维护，不参与 Prettier 格式化。

后端测试使用临时配置、日志、PID 和 SQLite，不读写日常数据。标记为 `integration` 的启停测试需要 macOS/Linux 的 `ps` 和进程信号权限；受限环境可单独运行 `pytest -m 'not integration'`，再在具备权限的环境运行完整测试。

```bash
pnpm --dir frontend exec playwright install chromium
pnpm --dir frontend test:e2e
```

页面测试将前端构建到本次临时目录的 `dist/`，使用临时 TOML、数据库、日志、PID 和独立服务，不清空或重建日常 `frontend/dist`。覆盖真实 API 连通、页面刷新、加载、错误重试、键盘、窄屏和 404。成功时清理临时目录，失败时打印诊断位置。macOS 受限沙箱需允许 Chromium 和本机进程控制。

页面测试支持 `pnpm --dir frontend test:e2e --config /absolute/path/app.test.toml`，文件必须包含全部配置。入口文件提供应用和测试设置；运行器始终将构建输出、数据库、日志、PID 和服务端口替换为本次隔离值，临时构建目录设置 `frontend_clean_output = false`，整体由运行器清理。直接执行 `pnpm exec playwright test` 会立即提示使用 `test:e2e`，避免遗漏隔离服务和 `baseURL`。

## 替换 Hello 示例

后端入口为 `routers/hello.py` → `services/hello.py` → `schemas/hello.py`；前端入口为 `pages/WelcomePage.tsx`，连接组件为 `components/ConnectionStatus.tsx`。

新增业务时，在 `models/` 定义并导出模型，在 `schemas/` 定义接口，在 `services/` 通过 AsyncSession 管理异步业务和写入事务，在 `routers/` 注册 HTTP 路由。生成并审查 Alembic 迁移，再接入前端 `api/`、`hooks/` 和页面，更新生成类型及测试。复杂复用查询出现后再提取 DAO。

索引与唯一约束的自动名称包含全部列。同一组列上的多个条件索引或表达式索引应显式命名。CheckConstraint 支持未命名建表；需要后续迁移管理时，应从首次定义起使用明确名称，例如 `CheckConstraint("quantity > 0", name="ck_items_positive_quantity")`。Alembic 的 autogenerate 不完整覆盖 CHECK 变更，必须人工审查和补齐迁移。
