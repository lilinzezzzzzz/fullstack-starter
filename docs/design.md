# 小型全栈脚手架设计

- 确认日期：2026-10-25
- 范围：本地、单用户、单机应用；V1 只有 Hello 示例
- 状态：已实现；历次实测结果见 [实现与验证记录](history.md)

本文描述当前架构和约束。[README](../README.md) 负责安装、运行和维护命令，[配置约定](configuration.md) 负责完整字段清单，历史变更不混入当前设计。

## 定位与运行方式

前后端放在同一个仓库，分别维护依赖和锁文件。FastAPI 提供 API，并托管 React SPA 的构建产物；依赖、数据库和前端产物准备好后，日常只运行一个 Python HTTP 服务。Node.js 只用于前端开发、检查和构建。

前端频繁修改时，可单独启动 Vite，由 Vite 将 `/api` 代理到后端。服务通过 `sh scripts/service.sh` 控制，依赖与检查直接使用 uv 和 pnpm，不引入 Makefile 或双进程开发管理器。本项目不依赖 `agent-backend` 的源码。

## 技术选型

| 领域 | 选型与职责 |
| --- | --- |
| 后端工具链 | Python 3.14.7、uv；`pyproject.toml` 和 `uv.lock` 固定依赖 |
| HTTP 与校验 | FastAPI、单 worker Uvicorn、Pydantic v2 |
| 应用配置 | TOML、原生 tomllib、Pydantic 严格校验 |
| 持久化 | SQLite、SQLAlchemy 2.0 AsyncEngine/AsyncSession、aiosqlite |
| 结构升级 | Alembic，通过异步连接的 run_sync 桥接执行迁移 |
| 日志 | Loguru，统一应用、请求和 Uvicorn 文件日志 |
| 前端工具链 | Node.js 24.22.0 LTS、pnpm 9.12.2、Vite、TypeScript |
| 页面与请求 | React、React Router、原生 fetch、TanStack Query |
| UI | Ant Design、CSS Modules；局部状态就地管理 |
| 接口类型 | openapi-typescript，从后端 OpenAPI 生成 TypeScript |
| 质量检查 | Ruff、pytest、ESLint、Prettier、TypeScript、Playwright Chromium |

具体库版本以两份锁文件为准，不根据文档描述自动升级依赖。解释器定位分别见 `backend/.python-version` 和根目录 `.node-version`。

## 目录结构

以下省略依赖和缓存目录，`.data/`、`.run/`、`logs/` 与 `dist/` 是运行产物。

```text
fullstack-starter/
├── README.md
├── AGENTS.md
├── .editorconfig
├── .gitignore
├── .node-version
├── configs/app.toml                  # 唯一应用配置入口
├── scripts/
│   ├── service.sh                    # start / stop / restart / status
│   ├── create-project.sh             # 创建项目的 sh 入口
│   └── create_project.py             # 复制、重命名、配置与锁文件校验
├── docs/
│   ├── design.md                     # 当前架构与 V1 范围
│   ├── configuration.md              # 必填配置及固定契约边界
│   └── history.md                    # 实现与验证记录
├── backend/
│   ├── pyproject.toml / uv.lock
│   ├── .python-version
│   ├── alembic.ini
│   ├── app/
│   │   ├── main.py                   # 应用工厂和 lifespan
│   │   ├── config.py                 # 配置读取、校验和路径解析
│   │   ├── path_safety.py            # 大小写/符号链接安全的运行路径边界
│   │   ├── service_state.py          # 启停与离线迁移共用的操作锁
│   │   ├── database.py               # 异步引擎、会话依赖和版本检查
│   │   ├── dependencies.py           # FastAPI 依赖提供器和 Service 组装
│   │   ├── api.py                    # API 路由装配
│   │   ├── frontend.py               # 静态托管与 SPA 回退边界
│   │   ├── errors.py / middleware.py # 错误、请求标识和访问边界
│   │   ├── logging_setup.py           # 日志初始化与 Uvicorn 桥接
│   │   ├── cli.py                    # 配置/OpenAPI 导出、迁移、备份命令
│   │   ├── routers/                  # hello.py、health.py
│   │   ├── services/                 # hello.py 业务服务
│   │   ├── maintenance/              # backup.py、CLI 维护基础设施
│   │   ├── models/                   # SQLAlchemy Base，无业务表
│   │   └── schemas/                  # Hello、健康检查与错误 Schema
│   ├── tools/
│   │   ├── __init__.py
│   │   └── service_control.py        # 服务进程、PID 与 Uvicorn 启动
│   ├── migrations/                   # 异步 Alembic 环境、初始版本
│   └── tests/                        # API、配置、数据库、静态托管、启停
├── frontend/
│   ├── package.json / pnpm-lock.yaml
│   ├── .npmrc / .prettierrc.toml / .prettierignore
│   ├── index.html / public/favicon.svg
│   ├── vite.config.ts / tsconfig.json
│   ├── eslint.config.js / playwright.config.ts
│   ├── scripts/                      # 统一配置、构建、类型和 E2E 工具
│   ├── src/
│   │   ├── main.tsx / App.tsx / router.tsx
│   │   ├── config.ts                 # 构建时注入的公开配置
│   │   ├── api/                      # HTTP 客户端、Hello 与健康检查
│   │   ├── hooks/useWelcome.ts        # 查询、连通状态与重试
│   │   ├── pages/                    # WelcomePage 及其 CSS Module
│   │   ├── components/               # ConnectionStatus 及其 CSS Module
│   │   ├── styles/global.css
│   │   └── types/api.generated.d.ts   # 自动生成，随源码维护
│   ├── e2e/welcome.spec.ts
│   └── dist/                         # 构建输出，不纳入 Git
├── .data/                            # app.sqlite3、backups/
├── logs/                             # app.log、service.log
└── .run/                             # 进程运行状态，不纳入 Git
    ├── fullstack-starter.pid          # 就绪后写入，正常停止后删除
    └── fullstack-starter.pid.lock     # 启停与维护互斥锁文件，可保留
```

后端与前端各自维护依赖；根目录不增加前端工作区包或统一运行器。随附目录及常见依赖、构建、日志、SQLite 辅助文件和私有文件模式被 Git 忽略；自定义运行路径需同步核对忽略规则。

`scripts/create_project.py` 是面向整个仓库的创建工具，仅依赖标准库，由 `create-project.sh` 调用；`backend/tools/service_control.py` 是后端进程工具，在后端环境中作为 `tools.service_control` 模块运行，复用应用配置、日志及工厂。依赖方向为工具调用应用，`app/` 保留运行基础和业务分层。Ruff 使用后端配置同时检查 `backend/` 和根目录的创建器。

`app/path_safety.py` 提供仅依赖标准库的路径保护规则，应用配置和创建器共同调用；`app/service_state.py` 提供启停与离线迁移共用的互斥锁，不反向依赖工具模块。

## 后端职责与数据库

| 层 | 职责与边界 |
| --- | --- |
| `routers/` | HTTP 参数、依赖声明、调用 Service、响应声明；不执行数据库写入 |
| `dependencies.py` | FastAPI 依赖提供器，从当前应用读取配置并组装 Service |
| `services/` | 业务类、业务规则、查询和写入事务；成功返回前提交，异常或取消时回滚 |
| `maintenance/` | CLI 专属维护基础设施，例如数据库快照；不承载 HTTP 业务 |
| `models/` | 持久化结构、索引与约束；不依赖 Router 或 Service |
| `schemas/` | 请求、响应和校验；与 ORM 模型分离 |

调用关系为 Router → Service → SQLAlchemy → SQLite。服务以类实现并通过构造参数接收依赖。HelloService 是无状态业务类，由 `dependencies.py` 中的 `new_hello_service` 读取当前应用的标题并构造；Router 直接通过 `Depends(new_hello_service)` 注入，服务不依赖 FastAPI 或 Pydantic。

数据库 I/O 使用 `async def` 和 `await`。每个请求或并发任务拥有独立 AsyncSession，写入使用 `async with session.begin()`，禁止共享会话和隐式关系加载。复杂查询出现真实复用需求后再增加 DAO，不预置通用 CRUD、Service 或 Repository 基类。

`create_app(settings)` 只装配应用。模块导入和 OpenAPI 导出不连接数据库、不创建日志、不要求前端产物存在。lifespan 检查前端产物和数据库版本，创建异步引擎与会话工厂，退出时 `await engine.dispose()`。

SQLite 使用本机文件系统，实际库版本至少为 3.51.3。连接启用外键、有限锁等待和显式 BEGIN；日志模式、持久化级别和池容量来自配置。WAL 保留单写入者约束，异步驱动不会将 SQLite 变成多写入者数据库。

3.51.3 是针对 WAL-reset 数据损坏修复的统一基线，并非 WAL 功能的最低支持版本。索引/唯一约束按全部列自动命名；CHECK 不强制套用名称模板，迁移管理所需的 CHECK 名称由模型显式给出。

初始迁移仅建立 Alembic 版本记录。建库与升级必须显式执行维护命令，正常启动不运行迁移或 `create_all()`。Alembic 的同步命令入口管理事件循环，通过 `AsyncConnection.run_sync()` 执行 DDL 桥接，不另建同步运行时引擎。已有数据的结构变更必须审查迁移，必要时使用 SQLite batch migration。

升级期间持有与服务控制器相同的操作锁；有 PID 文件时拒绝迁移，先通过同配置的 sh 入口停服。该锁防止受管理服务启动与迁移并发，不能代替停止手动启动的服务或其他数据库使用者。

备份实现在 `maintenance/backup.py`，由 `DatabaseBackup` 类接收配置依赖，CLI 负责参数、对象组装和事件循环。aiosqlite Backup API 创建独占命名的快照，校验完整性和迁移版本，不覆盖已有文件；取消时等待已提交的复制结束、关闭连接并清理未返回的结果，继续传播取消。恢复按 README 停服、验证副本、切换数据路径，不提供网页恢复入口。

## 前端与接口契约

TanStack Query 管理服务端状态，`api/client.ts` 负责请求超时、取消和错误解析；`useWelcome` 组合 Hello 与健康检查，页面和连接组件呈现加载、失败、成功及重试状态。保持现有 Hello 视觉设计，支持键盘操作和窄屏使用，不增加全局业务状态库。

| Method / 路径 | 契约 |
| --- | --- |
| `GET /api/v1/hello` | 欢迎信息，成功字段为 `message` |
| `GET /api/health` | 检查服务和真实 SQLite 连接 |
| `/`、`/welcome` | Hello 欢迎页，可直接访问和刷新 |
| `/docs`、`/openapi.json` | 文档与 Schema；开关和路径来自配置 |

成功响应直接返回 Schema；错误统一为 `code`、`message`、`details`、`request_id`。未预期的内部细节进入日志，不返回给浏览器。未知 API 和缺失静态资源返回真实 404；仅页面导航可回退到 SPA HTML。查询按配置有限重试，写请求重试次数必须显式配置为 0。

错误响应统一保留请求标识、no-store 和 nosniff；HTTP 异常仅透传 Allow、WWW-Authenticate、Retry-After 协议头。FastAPI 原生 OpenTelemetry 明确关闭，业务项目按需另行接入；Loguru 保持现有职责。

接口类型链路为 Pydantic Schema → CLI 导出 OpenAPI → openapi-typescript → `api.generated.d.ts`。生成文件由生成器维护，Prettier 忽略它；检查模式发现过期类型时失败而不改写文件。编译期类型不能代替服务端运行时校验。后续业务的时间按 UTC 保存和输出，API 使用带时区的 ISO 8601。

## 配置、访问与进程边界

全部 86 个叶子配置项及其分组均必填，唯一入口为 `configs/app.toml`。缺项、未知项、错误类型和非有限值明确失败；不从环境变量、`.env` 或旧 JSON 补值，不隐式合并配置。`0`、`false`、空列表保留其明确含义。固定入口位置、协议常量和安全规则留在代码，详见 [配置约定](configuration.md)。

相对数据、备份、日志、PID 和前端路径一律相对于项目根目录。构建工具复用 Python 校验器，只把 `client` 和应用标题/版本注入浏览器，私有路径和完整服务配置不打包。后端参数改动需重启，前端公开参数改动需重新构建。工具自身的 PATH、缓存位置和浏览器安装目录不作为应用配置来源。

随附 TOML 绑定 `127.0.0.1:18001`，Vite 使用 `127.0.0.1:5173` 并代理到后端。使用 Vite 时设置 `serve_frontend = false`；切回完整应用时设置 `serve_frontend = true` 并构建。Host 与 Origin 允许列表保护本机入口；局域网或远程共享需单独设计认证和访问策略。

服务始终单 worker，由 sh 入口管理。实际监听成功后才写入 PID；重复启动复用现有进程。停止前检查模块和启动配置路径，再发送 SIGTERM；正常退出清理 PID，超时保留且不强制杀进程，不按端口选择进程。启停必须使用同一配置文件路径，修改 PID 路径前先停止服务。

Loguru 将应用、请求标识和 Uvicorn 日志写入配置目录；启动早期输出进入独立的 `service.log`。不记录局部变量诊断。日志目录和 SQLite 数据目录随附配置均在项目根目录下。

## V1 范围与验收

| V1 内容 | 验收行为 |
| --- | --- |
| Hello 示例 | 唯一示例页面与 API，展示真实连通状态、加载、错误与重试 |
| 后端基础 | 应用工厂、严格配置、健康检查、统一错误、请求标识与日志 |
| 数据基础 | AsyncSession、显式事务、版本检查、初始迁移和手动备份 |
| 运行管理 | 单 FastAPI 服务、前端托管、可选 Vite、sh/PID 安全启停 |
| 接口协作 | 无副作用的 OpenAPI 导出、生成类型和一致性检查 |
| 工程质量 | 格式、lint、类型、后端与页面测试、运行和恢复说明 |

V1 不包含 CRUD 应用、业务表、登录权限、任务队列、Agent/RAG、对象存储、多租户、Docker 或 CI 模板，后续按实际任务增加。

后端测试使用独立临时配置、SQLite、日志和 PID，覆盖事务回滚、锁等待、并发会话隔离、取消清理、备份、静态回退和真实启停。页面测试通过 sh 启动独立服务，覆盖真实 API、刷新、404、加载、重试、键盘和窄屏；自动化以 Chromium 为基线。

E2E 的构建输出也位于本次临时目录，运行器强制替换入口配置中的输出位置并关闭目录自动清空，不重建日常 frontend/dist。独立 Playwright 配置会提示使用统一 E2E 入口。

安装、构建、迁移、启停、备份、类型与测试命令统一维护在 [README](../README.md)。测试数量和实测环境写入 [实现与验证记录](history.md)，不得由设计状态推断尚未执行的验证。

项目创建通过 `scripts/create-project.sh` 指定项目名、最终目标目录和后端端口，可另选 Vite 端口。创建工具排除运行与私有产物，调整项目元信息、配置和文档，仅修改 uv 锁文件中的本地项目名称并离线校验，保留第三方依赖记录。目标必须是脚手架之外的新目录，失败时清理本次创建的目标；依赖安装、建库、构建、Git 初始化和启动按 README 独立执行。示例测试按配置标题和端口断言，生成项目无需手动改测试文案。

复制前按共用路径策略拒绝运行路径与源码、遗留运行目录或依赖目录重叠，并检查创建所需的关键字段；复制后按源文件树校验 API、路由、服务、迁移、CLI、sh、前端和元信息入口，防止排除规则产生缺少源码的“成功”副本。完整的 Pydantic 配置语义仍由生成项目首次导出、测试或启动校验。

## 官方资料

- [FastAPI 多文件应用](https://fastapi.tiangolo.com/tutorial/bigger-applications/) 与 [异步说明](https://fastapi.tiangolo.com/async/)
- [SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) 与 [SQLite 方言](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html)
- [Alembic asyncio](https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic) 与 [SQLite batch migration](https://alembic.sqlalchemy.org/en/latest/batch.html)
- [SQLite WAL](https://www.sqlite.org/wal.html) 与 [Backup API](https://www.sqlite.org/backup.html)
- [aiosqlite API](https://aiosqlite.omnilib.dev/en/stable/api.html)、[Loguru](https://loguru.readthedocs.io/en/stable/api/logger.html)
- [Vite 静态构建](https://vite.dev/guide/static-deploy.html)、[开发代理](https://vite.dev/config/server-options#server-proxy)
- [openapi-typescript](https://openapi-ts.dev/introduction)、[Prettier CLI](https://prettier.io/docs/cli)
