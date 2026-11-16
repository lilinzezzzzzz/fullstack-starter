# 小型全栈脚手架设计

- 初始范围确认：2026-10-25；后续演进见历史记录
- 范围：本地、单用户、单机应用；V1 只有 Hello 示例
- 状态：已实现；历次实测结果见 [实现与验证记录](history.md)

本文描述当前架构和约束。[README](../README.md) 提供安装、运行和维护入口，[配置约定](configuration.md) 负责完整字段清单，历史变更不混入当前设计。已有项目如何逐步采用这些组织原则，见[架构对齐指南](project-alignment.md)。

## 定位与运行方式

前后端放在同一个仓库，分别维护依赖和锁文件。FastAPI 提供 API，并托管 React SPA 的构建产物；依赖、数据库和前端产物准备好后，日常只运行一个 Python HTTP 服务。Node.js 只用于前端开发、检查和构建。

前端频繁修改时，可单独启动 Vite，由 Vite 将 `/api` 代理到后端。服务通过 `sh entrypoints/service.sh run|start|status|stop|restart` 控制，依赖与检查直接使用 uv 和 pnpm，不引入 Makefile 或双进程开发管理器。

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
├── .prettierrc.toml                  # 前端与项目 Markdown 共用的格式规则
├── .prettierignore                   # 相对根目录的 Prettier 排除规则
├── configs/app.toml                  # 唯一应用配置入口
├── entrypoints/                      # 项目级 Shell 入口，不是 Python 包
│   └── service.sh                    # 定位后端环境并直接 exec Python
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
│   │   ├── application.py            # 应用工厂、路由装配和 lifespan
│   │   ├── config.py                 # 配置读取、校验和路径解析
│   │   ├── telemetry/                # 原生 telemetry 上下文装配
│   │   │   ├── __init__.py            # 轻量工厂导出入口
│   │   │   ├── environment.py         # 导入前环境隔离和 TOML 白名单桥接
│   │   │   └── provider.py            # 本地 SDK provider 和全局传播器装配
│   │   ├── utils/                    # 应用与工程工具共用的底层辅助模块
│   │   │   ├── database_lock.py      # 运行服务与离线迁移共用的数据库锁
│   │   │   └── path_safety.py        # 大小写/符号链接安全的运行路径边界
│   │   ├── infra/                    # 数据库、日志、静态托管与 HTTP 适配
│   │   │   ├── __init__.py           # 轻量包入口，无资源初始化
│   │   │   ├── database.py           # 异步引擎、会话依赖和版本检查
│   │   │   ├── errors.py             # 标准错误响应与异常处理器
│   │   │   ├── frontend.py           # 静态托管与 SPA 回退边界
│   │   │   ├── logging.py            # 日志配置与 Uvicorn 桥接
│   │   │   └── middleware.py         # ASGI 访问控制、trace 与请求日志
│   │   ├── routers/                  # hello.py、health.py
│   │   ├── services/                 # hello.py 业务类与同文件组装工厂
│   │   ├── maintenance/              # backup.py、CLI 维护基础设施
│   │   ├── models/                   # SQLAlchemy Base，无业务表
│   │   └── schemas/                  # Hello、健康检查与错误 Schema
│   ├── entrypoints/                  # 后端 Python 入口与服务控制实现
│   │   ├── __init__.py
│   │   ├── cli.py                    # 配置/OpenAPI 导出、迁移、备份命令
│   │   ├── service.py                # TOML 配置、前台运行与后台启停
│   │   └── service_control.py        # 实例身份、锁及本地认证控制通道
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
│   ├── .npmrc
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
├── .run/                             # instance.json、run.lock、control.lock、console.log
├── .data/                            # app.sqlite3、app.sqlite3.lock、backups/
└── logs/                             # app.log
```

后端与前端各自维护依赖；根目录不增加前端工作区包或统一运行器。随附目录及常见依赖、构建、日志、SQLite 辅助文件和私有文件模式被 Git 忽略；自定义运行路径需同步核对忽略规则。

项目根 `entrypoints/` 只存放 Shell 入口，`backend/entrypoints/` 保留 Python 实现，`scripts/` 存放项目生成等工程工具。`entrypoints/service.sh` 从自身位置向上一级定位项目根目录，再通过 `uv run --no-sync` 查询预装的 Python 解释器，切入后端目录并直接 `exec` 该解释器运行 `entrypoints.service`。uv 查询完成后退出，不常驻转发信号，Shell 启动 PID 即实际服务 PID，启停命令不触发依赖同步；后端 `service.py` 解析必填的 `run/start/status/stop/restart`，未指定 `--config` 时读取 `configs/app.toml`。前台 `run` 通过 Python loader 读取显式 TOML，后台子进程通过同一配置校验器消费父进程冻结的原始文档，不重新读取源文件；两者装配相同日志及工厂，通过 `uvicorn.Server.run()` 运行；`service_control.py` 负责实例身份、锁与认证控制通道，应用模块不依赖服务管理代码。`scripts/create_project.py` 是面向整个仓库的创建工具，仅依赖标准库，由 `create-project.sh` 调用。依赖方向为入口和工具调用应用，`app/` 保留运行基础和业务分层，不反向依赖可执行入口。Ruff 使用后端配置同时检查 `backend/` 和根目录的创建器。

`backend/entrypoints/cli.py` 作为 `entrypoints.cli` 运行，处理配置/OpenAPI 导出、数据库维护命令的参数、对象组装和事件循环边界；具体能力仍由应用配置、`app/maintenance/` 与 `backend/migrations/` 提供。应用模块不导入 CLI，前端工程工具通过子进程调用该入口。

`app/utils/` 存放供应用与工程工具复用的底层辅助模块，由调用方提供必要参数，包入口保持轻量。当前模块均仅依赖标准库：`path_safety.py` 提供应用配置和创建器共用的路径保护规则；`database_lock.py` 提供运行服务与离线迁移共用的数据库文件锁。辅助模块不反向依赖配置、业务服务或工具模块。

`app/infra/` 收拢数据库、日志、静态托管与通用 HTTP 适配，包入口只描述职责，不导入实现、注册组件或创建资源。`frontend.py` 提供构建产物检查和文件服务，应用工厂的 `_mount_frontend()` 决定是否挂载、传入配置并维护 API 优先顺序，lifespan 按需执行产物检查。`middleware.py` 负责 Host/Origin、trace、响应头与请求日志，`errors.py` 负责标准错误响应和异常到 HTTP 的映射，错误模型仍由 `schemas/common.py` 定义。应用工厂、服务入口、维护模块与迁移环境按需使用实现，资源创建和关闭仍由原有生命周期管理。配置模块保留原位，`utils/` 继续承担底层辅助职责。

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

`application.py` 按装配阶段拆成同文件函数：`create_app(settings)` 显式接收 Settings，创建本地 provider 与 FastAPI，保存应用级依赖并依次注册中间件、异常处理、API 路由、OpenAPI 配置与前端。单条中间件注册直接保留在工厂中，异常处理使用模块限定调用 `errors.register_error_handlers(application)`，随后装配 API、OpenAPI 与 SPA。

| 函数                                     | 职责                                                                                 |
| ---------------------------------------- | ------------------------------------------------------------------------------------ |
| `lifespan(application)`                  | 从当前应用状态取得配置与 provider，检查前端/数据库，创建引擎及会话工厂并清理运行资源 |
| `_register_api_routes(application)`      | 创建聚合路由，统一 `/api` 前缀和公共错误 Schema，按顺序注册 health 与 hello          |
| `_configure_openapi(application)`        | 在该应用的 OpenAPI 中补充公开的 ClientSettings Schema                                |
| `_mount_frontend(application, settings)` | 按配置挂载前端并维护保留路径，位于 API 注册之后                                      |

配置、数据库会话工厂与 trace provider 绑定具体应用，不新增全局 Settings 或数据库/provider 单例；Loguru 沿用现有进程级配置，具体 HTTP 处理器仍位于 `routers/`。模块导入和 OpenAPI 导出不连接数据库、不创建日志、不要求前端产物存在。模块级 lifespan 保持原有清理顺序：await 引擎释放后解锁，再关闭 provider 并等待日志队列；启动失败或取消继续传播，OpenAPI CLI 的 provider 仍由导出路径显式关闭。

SQLite 使用本机文件系统，实际库版本至少为 3.51.3。连接启用外键、有限锁等待和显式 BEGIN；日志模式、持久化级别和池容量来自配置。WAL 保留单写入者约束，异步驱动不会将 SQLite 变成多写入者数据库。

SQLite 完整性基线的依据见[数据库指南](database.md#sqlite-版本要求)；模型索引与约束命名见[模型约束约定](database.md#模型约束与命名)。

初始迁移仅建立 Alembic 版本记录。建库与升级必须显式执行维护命令，正常启动不运行迁移或 `create_all()`。Alembic 的同步命令入口管理事件循环，通过 `AsyncConnection.run_sync()` 执行 DDL 桥接，不另建同步运行时引擎。已有数据的结构变更必须审查迁移，必要时使用 SQLite batch migration。

迁移代码集中在 `backend/migrations/`：`operations.py` 管理 Alembic 配置、head 查询和带停服保护的升级；`env.py` 复用引擎构造并执行 DDL；`versions/` 保存历史；`development.py` 负责隔离临时库上的重放、生成与检查。运行时 `app/infra/database.py` 通过 operations 查询期望版本，operations 不反向依赖引擎模块，避免循环依赖。开发命令不连接日常库，应用数据库升级仍需显式执行。

生成、审查、旧数据回归、迁移脚本能力及恢复边界统一见[数据库指南](database.md#迁移生成审查与验证)。测试中真实历史重放与合成机制验证分开，baseline 的空表断言只针对 `0001_baseline`。

应用 lifespan 与离线升级持有同一个数据库文件锁，防止相同数据库的重复服务或迁移并发；启动时先检查数据库存在，关闭连接后释放锁。维护前直接执行 `stop`，或在前台服务终端按 Ctrl+C，并确认清理完成；维护 CLI 仍需指定目标数据库的完整配置。锁路径从实际数据库路径派生，例如 `.data/app.sqlite3.lock`，文件可保留，运行期间不删除；该机制只约束使用它的本机进程，其他数据库使用者也必须先停止。

`maintenance/backup.py` 的 `DatabaseBackup` 接收配置，异步创建并校验独占命名的快照；CLI 负责参数、组装和事件循环。备份对象不管理服务状态，停服、版本匹配与恢复副本的操作步骤见[数据库指南](database.md#数据库与备份)。

## 前端与接口契约

TanStack Query 管理服务端状态，`api/client.ts` 负责请求超时、取消和错误解析；`useWelcome` 组合 Hello 与健康检查，页面和连接组件呈现加载、失败、成功及重试状态。保持现有 Hello 视觉设计，支持键盘操作和窄屏使用，不增加全局业务状态库。

| Method / 路径                      | 契约                                  |
| ---------------------------------- | ------------------------------------- |
| `GET /api/v1/hello`                | 固定返回 `{"message": "Hello World"}` |
| `GET /api/health`                  | 检查服务和真实 SQLite 连接            |
| `/`、`/welcome`                    | Hello 欢迎页，可直接访问和刷新        |
| `/docs`、`/redoc`、`/openapi.json` | 文档与 Schema；开关和路径来自配置     |

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

服务始终单 worker，Shell 只定位环境并转发参数，Python 入口提供五个必填子命令。`run` 前台运行，`start` 以独立会话启动同一 `run` 路径，等待该实例的 Uvicorn 已启动且健康 API 返回数据库正常；只创建进程不算成功。后台标准输出与错误追加到项目根 `.run/console.log`，启动失败给出该路径及应用日志位置。不会执行依赖安装、数据库迁移或前端构建。

项目根目录固定使用 `.run/control.lock`、`.run/run.lock` 和 `.run/instance.json`。每个项目只管理一个实例；命令锁以有期限的等待串行执行五个命令，前台 `run` 在完成实例登记后释放命令锁，运行锁覆盖完整生命周期和末尾日志清理。运行期间不删除锁文件。状态记录仅在运行锁持有时有效，遗留记录不能作为向 PID 发信号的依据。

`start/run` 在操作锁内先认证已有实例，已有实例时提示并返回 0，不读取指定配置；无实例才读取完整 TOML。`status/stop` 只读取已保存的实例身份、实际 URL、日志和停止期限，不读取 TOML，不因配置变化报告 config-changed。`restart` 在锁内读取、校验并冻结目标配置，然后停止当前实例并后台启动，配置路径可以不同；省略 `--config` 固定选择 `configs/app.toml`。目标在锁内读取时无效则不停止旧实例，校验后的原文件再变化也不影响快照。通用配置解析接口由 `app/config.py` 提供，服务控制代码不写入任何项目特有配置字段。

后台启动通过匿名继承描述符传递原始 TOML 文档和规范化来源路径，子进程不重新打开原文件；原始配置快照只通过匿名描述符传递，不进入具名文件、日志或参数。控制通道随机令牌仅写入 0600 的 `.run/instance.json` 及原子替换期间同权限的 `instance.json.pending`，不进入配置快照、日志、命令行或 Git。状态文件协议版本为 1，以 0600 权限原子写入，包含 PID、UTC 启动时间、规范化公开启动命令、项目根、来源路径、快照指纹、认证控制端口、随机凭据、实际 HTTP 地址、日志与停止期限。`command` 去除内部 `--settings-fd`，可重新调用公开入口，但不携带原启动快照，也不承诺重新加载时的配置与原快照一致。控制通道仅监听回环地址，验证凭据、PID 与指纹；停止请求由目标进程向自身发送 SIGINT，不从外部按文件 PID 或端口发信号。路径保护在运行文件边界执行，不因不加载配置而失效；旧的活跃实例协议不能被新版本接管，升级前先用原版本停服。

`[service]` 提供启动和停止期限，停止期限须大于 Uvicorn 优雅关闭期限。成功返回 0，`status` 已停止返回 3，其他不健康状态或执行错误为 1，参数错误为 2，所有 Ctrl+C 中断为 130。前台 `run` 收到 Ctrl+C 先沿用 Uvicorn 完成优雅停服，返回 130；SIGTERM 同样完成资源、日志和实例清理后返回 143。末尾清理忽略重复 SIGINT/SIGTERM，之后恢复原处理器。停止或回收超时保留实例且不强杀，restart 不继续启动。命令锁等待上限为 40 秒，单次控制连接为 0.5 秒，HTTP 健康探测默认 1 秒；启动期探测取默认值与剩余启动期限中的较小值。运行锁已占用但身份尚未登记时，start/run 返回 0 仅表示不再启动第二实例；status 返回 starting/1，stop 因身份不明返回 1，不发信号。

资源先由 lifespan 关闭，入口随后排空末尾日志、关闭控制线程并移除实例记录，最后释放运行锁；末尾清理期间临时忽略重复 SIGINT，随后恢复处理器。运行期间仍保留 Uvicorn 原生信号行为，不注册开机自启、崩溃重拉或业务后台任务。

E2E 由 Playwright 向自有服务进程组发送 SIGINT，沿用前台 Ctrl+C 的原生关闭路径，使服务入口的日志排空与 Python 退出清理完成。运行器收到 SIGINT/SIGTERM 或命令超时时，也先向自有子进程组发送 SIGINT，保留既有等待期限与 SIGKILL 兜底。Uvicorn 在优雅关闭后重发信号；入口把重发的 SIGTERM 转为可展开 Python 清理栈的 143 退出，避免默认终止动作跳过实例清理。服务控制命令与后端测试辅助器超时不强杀；E2E 的 SIGKILL 仅是回收自有临时进程的例外，命令超时始终失败并保留诊断。强制终止不保证资源清理或日志完整写入。

`app/infra/logging.py` 提供 `configure_logging(settings)`，标准库日志模块使用 `std_logging` 别名，与 Loguru 的 `logger` 实例区分；应用工厂与服务入口负责调用，infra 包入口不自动初始化日志。Loguru 将应用、链路标识和 Uvicorn 日志通过 `enqueue=True` 交给后台线程写入配置目录；配置与导入阶段的错误直接显示在终端；运行日志由 `logging.console` 决定是否同时输出到终端。应用 lifespan 清理时和服务入口退出时等待日志队列处理完成，不记录局部变量诊断。日志目录和 SQLite 数据目录随附配置均在项目根目录下。

## V1 范围与验收

| V1 内容    | 验收行为                                                                   |
| ---------- | -------------------------------------------------------------------------- |
| Hello 示例 | 唯一示例页面与 API，展示真实连通状态、加载、错误与重试                     |
| 后端基础   | 应用工厂、严格配置、健康检查、统一错误、链路标识与日志                     |
| 数据基础   | AsyncSession、显式事务、版本检查、初始迁移和手动备份                       |
| 运行管理   | 单 FastAPI 服务、前端托管、可选 Vite、前台运行/后台启停与 Uvicorn 优雅关闭 |
| 接口协作   | 不连接数据库的 OpenAPI 导出、生成类型和一致性检查                          |
| 工程质量   | 格式、lint、类型、后端与页面测试、运行和恢复说明                           |

V1 不包含 CRUD 应用、业务表、登录权限、任务队列、Agent/RAG、对象存储、多租户、Docker 或 CI 模板，后续按实际任务增加。

后端测试使用独立临时配置、SQLite 和日志，覆盖事务回滚、锁等待、并发会话隔离、取消清理、备份、静态回退和真实启停。后端服务测试和页面测试均使用独立临时后端项目副本，固定 `.run/` 属于该副本；只复用已安装依赖，不复用日常服务状态。页面测试由 Playwright 通过副本的 sh 启动独立前台服务，等待健康检查并在结束后优雅关闭，覆盖真实 API、刷新、404、加载、重试、键盘和窄屏；自动化以 Chromium 为基线。

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
