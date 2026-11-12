# 小型全栈脚手架设计

- 初始范围确认：2026-10-25；后续演进见历史记录
- 范围：本地、单用户、单机应用；V1 只有 Hello 示例
- 状态：已实现；历次实测结果见 [实现与验证记录](history.md)

本文描述当前架构和约束。[README](../README.md) 提供安装、运行和维护入口，[配置约定](configuration.md) 负责完整字段清单，历史变更不混入当前设计。已有项目如何逐步采用这些组织原则，见[架构对齐指南](project-alignment.md)。

## 定位与运行方式

前后端放在同一个仓库，分别维护依赖和锁文件。FastAPI 提供 API，并托管 React SPA 的构建产物；依赖、数据库和前端产物准备好后，日常只运行一个 Python HTTP 服务。Node.js 只用于前端开发、检查和构建。

前端频繁修改时，可单独启动 Vite，由 Vite 将 `/api` 代理到后端。服务通过 `sh entrypoints/service.sh` 控制，依赖与检查直接使用 uv 和 pnpm，不引入 Makefile 或双进程开发管理器。

## 技术选型

| 领域        | 选型与职责                                                      |
| ----------- | --------------------------------------------------------------- |
| 后端工具链  | Python、uv；`pyproject.toml` 和 `uv.lock` 固定依赖              |
| HTTP 与校验 | FastAPI、单 worker Uvicorn、Pydantic v2                         |
| 应用配置    | TOML、原生 tomllib、Pydantic 严格校验                           |
| 持久化      | SQLite、SQLAlchemy 2.0 AsyncEngine/AsyncSession、aiosqlite      |
| 结构升级    | Alembic，通过异步连接的 run_sync 桥接执行迁移                   |
| 日志        | Loguru，统一应用、请求和 Uvicorn 文件日志                       |
| 前端工具链  | Node.js、pnpm、Vite、TypeScript                                 |
| 页面与请求  | React、React Router、原生 fetch、TanStack Query                 |
| UI          | Ant Design、CSS Modules；局部状态就地管理                       |
| 接口类型    | openapi-typescript，从后端 OpenAPI 生成 TypeScript              |
| 质量检查    | Ruff、pytest、ESLint、Prettier、TypeScript、Playwright Chromium |

具体库版本以两份锁文件为准，不根据文档描述自动升级依赖。解释器定位分别见 `backend/.python-version` 和根目录 `.node-version`，pnpm 版本见 `frontend/package.json`。

## 目录结构

以下省略依赖、缓存与子目录 AGENTS；指令入口见[根规则](../AGENTS.md#范围与指令入口)。`.data/`、`logs/` 与 `dist/` 是运行产物。

```text
fullstack-starter/
├── README.md
├── AGENTS.md
├── .editorconfig
├── .gitignore
├── .node-version
├── configs/app.toml                  # 唯一应用配置入口
├── entrypoints/                      # 应用与服务启动入口
│   └── service.sh                    # 前台启动，Ctrl+C 停止
├── scripts/                          # 工程工具
│   ├── create-project.sh             # 创建项目的 sh 入口
│   └── create_project.py             # 复制、重命名、配置与锁文件校验
├── docs/
│   ├── design.md                     # 当前架构与 V1 范围
│   ├── configuration.md              # 必填配置及固定契约边界
│   ├── project-alignment.md          # 已有项目的差异分析与渐进对齐
│   ├── project-creation.md           # 独立项目创建流程与复制边界
│   ├── database.md                   # 数据库备份、恢复与迁移操作
│   └── history.md                    # 实现与验证记录
├── backend/
│   ├── pyproject.toml / uv.lock
│   ├── .python-version
│   ├── alembic.ini
│   ├── app/
│   │   ├── main.py                   # 应用工厂和 lifespan
│   │   ├── config.py                 # 配置读取、校验和路径解析
│   │   ├── telemetry/                # 原生 telemetry 上下文装配
│   │   │   ├── __init__.py            # 轻量工厂导出入口
│   │   │   ├── environment.py         # 导入前环境隔离和 TOML 白名单桥接
│   │   │   └── provider.py            # 本地 SDK provider 和全局传播器装配
│   │   ├── utils/                    # 应用与工程工具共用的底层辅助模块
│   │   │   ├── database_lock.py      # 运行服务与离线迁移共用的数据库锁
│   │   │   └── path_safety.py        # 大小写/符号链接安全的运行路径边界
│   │   ├── database.py               # 异步引擎、会话依赖和版本检查
│   │   ├── api.py                    # API 路由装配
│   │   ├── frontend.py               # 静态托管与 SPA 回退边界
│   │   ├── errors.py / middleware.py # 错误、链路标识和访问边界
│   │   ├── logging_setup.py           # 日志初始化与 Uvicorn 桥接
│   │   ├── cli.py                    # 配置/OpenAPI 导出、迁移、备份命令
│   │   ├── routers/                  # hello.py、health.py
│   │   ├── services/                 # hello.py 业务类与同文件组装工厂
│   │   ├── maintenance/              # backup.py、CLI 维护基础设施
│   │   ├── models/                   # SQLAlchemy Base，无业务表
│   │   └── schemas/                  # Hello、健康检查与错误 Schema
│   ├── tools/
│   │   ├── __init__.py
│   │   └── service_control.py        # TOML 配置与前台 Uvicorn 启动
│   ├── migrations/
│   │   ├── __init__.py               # 迁移包，不在导入时执行迁移
│   │   ├── operations.py             # Alembic 配置、head 查询、显式升级
│   │   ├── development.py            # 临时库重放、迁移生成与检查
│   │   ├── env.py                    # 异步 Alembic 执行环境
│   │   ├── script.py.mako            # 新 revision 模板
│   │   └── versions/                 # 初始版本及后续迁移历史
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
├── .data/                            # app.sqlite3、app.sqlite3.lock、backups/
└── logs/                             # app.log
```

后端与前端各自维护依赖；根目录不增加前端工作区包或统一运行器。随附目录及常见依赖、构建、日志、SQLite 辅助文件和私有文件模式被 Git 忽略；自定义运行路径需同步核对忽略规则。

`entrypoints/` 存放应用与服务的启动脚本，`scripts/` 存放项目生成等工程工具。`scripts/create_project.py` 是面向整个仓库的创建工具，仅依赖标准库，由 `create-project.sh` 调用；`backend/tools/service_control.py` 是前台启动的 Python 实现，在后端环境中作为 `tools.service_control` 模块运行，读取应用配置、装配日志及工厂，然后直接调用 `uvicorn.run()`。依赖方向为工具调用应用，`app/` 保留运行基础和业务分层。Ruff 使用后端配置同时检查 `backend/` 和根目录的创建器。

`app/utils/` 存放供应用与工程工具复用的底层辅助模块，由调用方提供必要参数，包入口保持轻量。当前模块均仅依赖标准库：`path_safety.py` 提供应用配置和创建器共用的路径保护规则；`database_lock.py` 提供运行服务与离线迁移共用的数据库文件锁。辅助模块不反向依赖配置、业务服务或工具模块。

## 后端职责与数据库

| 层             | 职责与边界                                                                                   |
| -------------- | -------------------------------------------------------------------------------------------- |
| `routers/`     | HTTP 参数、依赖声明、调用 Service、响应声明；不执行数据库写入                                |
| `services/`    | 业务类负责业务规则、查询和写入事务，成功返回前提交、异常或取消时回滚；同文件工厂负责依赖组装 |
| `maintenance/` | CLI 专属维护基础设施，例如数据库快照；不承载 HTTP 业务                                       |
| `models/`      | 持久化结构、索引与约束；不依赖 Router 或 Service                                             |
| `schemas/`     | 请求、响应和校验；与 ORM 模型分离                                                            |

调用关系为 Router → Service → SQLAlchemy → SQLite。服务类通过构造参数接收业务依赖，类内不处理 FastAPI 请求或依赖解析，也不构造 Pydantic I/O Schema 或基础设施。

各服务的 `new_*_service` 作为模块级工厂，与业务类放在同一文件中，负责框架适配和依赖组装。服务模块可以按需导入 FastAPI，业务类自身不感知 HTTP。HelloService 无状态、无外部依赖，固定返回 `Hello World`；`services/hello.py` 中的无参工厂 `new_hello_service` 使用 `functools.cache`，在缓存命中后跨请求复用服务实例，不持有请求或配置。Router 从同一模块导入服务类和工厂，并通过 `Depends(new_hello_service)` 注入。

数据库 I/O 使用 `async def` 和 `await`。每个请求或并发任务拥有独立 AsyncSession，写入使用 `async with session.begin()`，禁止共享会话和隐式关系加载。复杂查询出现真实复用需求后再增加 DAO，不预置通用 CRUD、Service 或 Repository 基类。

`create_app(settings)` 只装配应用。模块导入和 OpenAPI 导出不连接数据库、不创建日志、不要求前端产物存在。lifespan 检查前端产物和数据库版本，创建异步引擎与会话工厂，退出时 `await engine.dispose()`。

SQLite 使用本机文件系统，实际库版本至少为 3.51.3。连接启用外键、有限锁等待和显式 BEGIN；日志模式、持久化级别和池容量来自配置。WAL 保留单写入者约束，异步驱动不会将 SQLite 变成多写入者数据库。

SQLite 完整性基线的依据见[数据库指南](database.md#sqlite-版本要求)；模型索引与约束命名见[模型约束约定](database.md#模型约束与命名)。

初始迁移仅建立 Alembic 版本记录。建库与升级必须显式执行维护命令，正常启动不运行迁移或 `create_all()`。Alembic 的同步命令入口管理事件循环，通过 `AsyncConnection.run_sync()` 执行 DDL 桥接，不另建同步运行时引擎。已有数据的结构变更必须审查迁移，必要时使用 SQLite batch migration。

迁移代码集中在 `backend/migrations/`：`operations.py` 管理 Alembic 配置、head 查询和带停服保护的升级；`env.py` 复用引擎构造并执行 DDL；`versions/` 保存历史；`development.py` 负责隔离临时库上的重放、生成与检查。运行时 `app/database.py` 通过 operations 查询期望版本，operations 不反向依赖引擎模块，避免循环依赖。开发命令不连接日常库，应用数据库升级仍需显式执行。

生成、审查、旧数据回归、迁移脚本能力及恢复边界统一见[数据库指南](database.md#迁移生成审查与验证)。测试中真实历史重放与合成机制验证分开，baseline 的空表断言只针对 `0001_baseline`。

应用 lifespan 与离线升级持有同一个数据库文件锁，防止相同数据库的重复服务或迁移并发；启动时先检查数据库存在，关闭连接后释放锁。维护前按 Ctrl+C 停止服务。锁路径从实际数据库路径派生，例如 `.data/app.sqlite3.lock`，文件可保留，运行期间不删除；该机制只约束使用它的本机进程，其他数据库使用者也必须先停止。

`maintenance/backup.py` 的 `DatabaseBackup` 接收配置，异步创建并校验独占命名的快照；CLI 负责参数、组装和事件循环。备份对象不管理服务状态，停服、版本匹配与恢复副本的操作步骤见[数据库指南](database.md#数据库与备份)。

## 前端与接口契约

TanStack Query 管理服务端状态，`api/client.ts` 负责请求超时、取消和错误解析；`useWelcome` 组合 Hello 与健康检查，页面和连接组件呈现加载、失败、成功及重试状态。保持现有 Hello 视觉设计，支持键盘操作和窄屏使用，不增加全局业务状态库。

| Method / 路径            | 契约                                  |
| ------------------------ | ------------------------------------- |
| `GET /api/v1/hello`      | 固定返回 `{"message": "Hello World"}` |
| `GET /api/health`        | 检查服务和真实 SQLite 连接            |
| `/`、`/welcome`          | Hello 欢迎页，可直接访问和刷新        |
| `/docs`、`/openapi.json` | 文档与 Schema；开关和路径来自配置     |

成功响应直接返回 Schema；错误统一为 `code`、`message`、`details`、`trace_id`。未预期的内部细节进入日志，不返回给浏览器。未知 API 和缺失静态资源返回真实 404；仅页面导航可回退到 SPA HTML。查询按配置有限重试，写请求重试次数必须显式配置为 0。

FastAPI 原生 telemetry 使用应用显式创建的本地 SDK `TracerProvider` 管理请求上下文。官方 W3C propagator 解析 `traceparent`：有效时继承 trace ID，缺失或无效时由 SDK 创建新的 trace ID；每次请求均创建新的服务端 span ID。ID 由 SDK 的随机生成器提供，不再校验 UUID 版本。字段长度、大小写、全零值和版本扩展由官方解析器判断；1.45.1 容忍头部两端空白，对重复请求头使用首个值，不叠加自定义解析规则。[FastAPI 原生 telemetry](https://fastapi.tiangolo.com/advanced/opentelemetry/)

采样器固定为 `ALWAYS_OFF`。原生请求 span 使用不记录数据的上下文；metrics、OTel logs、operation_spans、SDK 内部指标与自动导出全部关闭，provider 不注册采集/导出 processor 或 exporter。即使上游标记为采样，也不会启用本地记录。业务项目如需采集，应另行设计配置和数据处理边界。

请求中间件读取当前有效 span 的 trace ID，并写入 `request.state.trace_id`、Loguru 上下文和错误体。官方 propagator 在请求入口将本次服务端上下文序列化为 `traceparent`，保存在请求状态，并用于正常和错误响应头。格式为 `00-<32 位 trace ID>-<16 位服务端 span ID>-<2 位 flags>`；服务端 span ID 与上游 parent ID 不同，flags 采用 SDK 当前值，采样位关闭。只返回 `traceparent`，不额外回传 `tracestate`。

500 处理器从请求状态恢复日志上下文和保存的响应头，保证中间件退出后仍关联本次服务端 span。同一链路的请求可以共享 trace ID；不再提供 `X-Trace-ID`、`request_id` 或 `X-Request-ID`。错误响应继续保留 no-store 和 nosniff，HTTP 异常仅透传 Allow、WWW-Authenticate、Retry-After 协议头。前端错误对象继续从错误体读取 `trace_id`，不依赖自定义响应头。

`app/telemetry/` 负责导入前环境隔离、本地 provider 装配和全局传播器安装；不替换全局 tracer/meter/logger provider。lifespan 在正常退出及启动失败时关闭 provider，OpenAPI CLI 在导出后显式关闭。具体开关、环境白名单和进程边界统一见[配置约定](configuration.md#遥测上下文与环境隔离)。

接口类型链路为 Pydantic Schema → CLI 导出 OpenAPI → openapi-typescript → `api.generated.d.ts`。生成文件由生成器维护，Prettier 忽略它；检查模式发现过期类型时失败而不改写文件。编译期类型不能代替服务端运行时校验。后续业务的时间按 UTC 保存和输出，API 使用带时区的 ISO 8601。

## 配置、访问与进程边界

全部配置字段及分组均必填，固定引导入口为 `configs/app.toml`，CLI 可通过 `--config` 显式选择另一份完整 TOML。缺项、未知项、错误类型和非有限值明确失败；不从环境变量、`.env` 或旧 JSON 补值，不隐式合并配置。`0`、`false`、空列表保留其明确含义。固定入口位置、协议常量和安全规则留在代码，详见 [配置约定](configuration.md)。

相对数据、备份、日志和前端路径一律相对于项目根目录。构建工具复用 Python 校验器，只把 `client` 和应用标题/版本注入浏览器，私有路径和完整服务配置不打包。后端参数改动需重启，前端公开参数改动需重新构建。工具自身的 PATH、缓存位置和浏览器安装目录不作为应用配置来源。

随附 TOML 绑定 `127.0.0.1:18001`，Vite 使用 `127.0.0.1:5173` 并代理到后端。使用 Vite 时设置 `serve_frontend = false`；切回完整应用时设置 `serve_frontend = true` 并构建。Host 与 Origin 允许列表保护本机入口；局域网或远程共享需单独设计认证和访问策略。

服务始终单 worker，由 sh 入口在前台运行。Uvicorn 处理 Ctrl+C、SIGTERM 与优雅关闭；不创建后台子进程、PID 文件、就绪管道或启停轮询。重复服务和端口占用均明确失败，不按端口选择或终止进程；重启通过停止后再次执行启动命令完成。

Loguru 将应用、链路标识和 Uvicorn 日志通过 `enqueue=True` 交给后台线程写入配置目录；配置与导入阶段的错误直接显示在终端；运行日志由 `logging.console` 决定是否同时输出到终端。应用 lifespan 清理时和服务入口退出时等待日志队列处理完成，不记录局部变量诊断。日志目录和 SQLite 数据目录随附配置均在项目根目录下。

## V1 范围与验收

| V1 内容    | 验收行为                                                             |
| ---------- | -------------------------------------------------------------------- |
| Hello 示例 | 唯一示例页面与 API，展示真实连通状态、加载、错误与重试               |
| 后端基础   | 应用工厂、严格配置、健康检查、统一错误、链路标识与日志               |
| 数据基础   | AsyncSession、显式事务、版本检查、初始迁移和手动备份                 |
| 运行管理   | 单 FastAPI 服务、前端托管、可选 Vite、sh 前台启动与 Uvicorn 优雅关闭 |
| 接口协作   | 不连接数据库的 OpenAPI 导出、生成类型和一致性检查                    |
| 工程质量   | 格式、lint、类型、后端与页面测试、运行和恢复说明                     |

V1 不包含 CRUD 应用、业务表、登录权限、任务队列、Agent/RAG、对象存储、多租户、Docker 或 CI 模板，后续按实际任务增加。

后端测试使用独立临时配置、SQLite 和日志，覆盖事务回滚、锁等待、并发会话隔离、取消清理、备份、静态回退和真实启停。页面测试由 Playwright 通过 sh 启动独立前台服务，等待健康检查并在结束后优雅关闭，覆盖真实 API、刷新、404、加载、重试、键盘和窄屏；自动化以 Chromium 为基线。

E2E 的构建输出也位于本次临时目录，运行器强制替换入口配置中的输出位置并关闭目录自动清空，不重建日常 frontend/dist。独立 Playwright 配置会提示使用统一 E2E 入口。

安装、构建、启停、类型与测试命令以 [README](../README.md) 为入口；[数据库指南](database.md)保存维护与迁移的详细步骤，[项目创建指南](project-creation.md)保存复制与初始化流程。测试数量和实测环境写入 [实现与验证记录](history.md)，不得由设计状态推断尚未执行的验证。

项目创建由 `scripts/create-project.sh` 调用标准库实现，复用路径策略并检查副本完整性；仅调整项目元信息和本地锁条目，保留第三方依赖。参数、复制排除、配置校验能力及后续准备统一见[项目创建指南](project-creation.md)。

## 官方资料

- [FastAPI 多文件应用](https://fastapi.tiangolo.com/tutorial/bigger-applications/) 与 [异步说明](https://fastapi.tiangolo.com/async/)
- [SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) 与 [SQLite 方言](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html)
- [Alembic asyncio](https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic) 与 [SQLite batch migration](https://alembic.sqlalchemy.org/en/latest/batch.html)
- [SQLite WAL](https://www.sqlite.org/wal.html) 与 [Backup API](https://www.sqlite.org/backup.html)
- [aiosqlite API](https://aiosqlite.omnilib.dev/en/stable/api.html)、[Loguru](https://loguru.readthedocs.io/en/stable/api/logger.html)
- [Vite 静态构建](https://vite.dev/guide/static-deploy.html)、[开发代理](https://vite.dev/config/server-options#server-proxy)
- [openapi-typescript](https://openapi-ts.dev/introduction)、[Prettier CLI](https://prettier.io/docs/cli)
