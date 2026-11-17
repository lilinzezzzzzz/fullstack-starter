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
├── configs/app.toml                  # 其余应用与工具配置
├── entrypoints/                      # 项目级 Shell 入口，不是 Python 包
│   └── service.sh                    # 唯一服务入口，五个命令及 Uvicorn CLI 启动
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
│   │   ├── application.py            # 无参数应用工厂、路由装配和 lifespan
│   │   ├── config.py                 # 固定 settings 代理、真实实例缓存、校验和路径解析
│   │   ├── telemetry/                # 原生 telemetry 上下文装配
│   │   │   ├── __init__.py            # 轻量作用域与 getter 导出入口
│   │   │   ├── environment.py         # 导入前环境隔离和 TOML 白名单桥接
│   │   │   ├── provider.py            # 本地 SDK provider 生命周期与传播器装配
│   │   │   └── adapter.py             # 不持有 SDK 资源的公共 API 适配入口
│   │   ├── utils/                    # 应用与工程工具共用的底层辅助模块
│   │   │   ├── database_lock.py      # 运行服务与离线迁移共用的数据库锁
│   │   │   ├── lazy_proxy.py         # 仅转发属性读取的轻量代理
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
│   ├── entrypoints/                  # ASGI 暴露及配置导出、维护入口
│   │   ├── __init__.py
│   │   ├── cli.py                    # 配置/OpenAPI 导出、迁移、备份命令
│   │   └── api.py                    # 仅导入 create_app，app = create_app()
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
├── .run/                             # instance.json、console.log，不存放服务锁
├── .data/                            # app.sqlite3、app.sqlite3.lock、backups/
└── logs/                             # app.log
```

后端与前端各自维护依赖；根目录不增加前端工作区包或统一运行器。随附目录及常见依赖、构建、日志、SQLite 辅助文件和私有文件模式被 Git 忽略；自定义运行路径需同步核对忽略规则。

根 entrypoints 只放 service.sh，直接实现五个管理命令。ps 提供 PID/启动时间，jq 读写记录，stat 检查权限，lsof/curl 检查监听和健康，Shell 发信号并用自有 sleep 子进程处理等待预算。后台使用 nohup，忽略 SIGHUP，不再创建 Python 独立会话。Python 只校验/导出配置 JSON、装配应用和日志，service_control.py 已删除；status/stop 不调用 Python/uv。运维负责串行管理，不提供服务锁。

`backend/entrypoints/cli.py` 作为 `entrypoints.cli` 运行，处理配置/OpenAPI 导出、数据库维护命令的参数、对象组装和事件循环边界；具体能力仍由应用配置、`app/maintenance/` 与 `backend/migrations/` 提供。应用模块不导入 CLI，前端工程工具通过子进程调用该入口。

`app/utils/` 存放供应用与工程工具复用的底层辅助模块，由调用方提供必要参数，包入口保持轻量。当前模块均仅依赖标准库：`path_safety.py` 提供应用配置和创建器共用的路径保护规则；`database_lock.py` 提供运行服务与离线迁移共用的数据库文件锁；`lazy_proxy.py` 只将属性读取转发给传入的 getter，不持有配置缓存。辅助模块不反向依赖配置、业务服务或工具模块。

`app/infra/` 收拢数据库、日志、静态托管与通用 HTTP 适配，包入口只描述职责，不导入实现、注册组件或创建资源。`frontend.py` 的 `FrontendFiles()` 和 `check_frontend_directory()` 直接读取 settings，不再由应用工厂转传构建目录和文档保留路径；`_mount_frontend()` 决定是否挂载并维护 API 优先顺序。文件服务构造时不检查产物，lifespan 按需执行检查。`middleware.py` 负责 Host/Origin、trace、响应头与请求日志，`errors.py` 负责标准错误响应和异常到 HTTP 的映射，错误模型仍由 `schemas/common.py` 定义。应用工厂、服务入口、维护模块与迁移环境按需使用实现，资源创建和关闭仍由原有生命周期管理。配置模块保留原位，`utils/` 继续承担底层辅助职责。

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

普通运行时模块顶部直接 from app.config import settings，函数执行时读取属性；CLI 和测试保留加载、getter 和绑定接口，telemetry 轻量入口继续函数内导入。create_app() 先桥接白名单，注入无 SDK 资源适配器，再装配中间件、异常处理、API、OpenAPI 和前端；真实 provider 只在生命周期内创建，不保存到 app.state，API 先于 SPA。

| 函数                                | 职责                                                                               |
| ----------------------------------- | ---------------------------------------------------------------------------------- |
| `lifespan(application)`             | 先初始化日志，进入 provider 和 Session 工厂作用域，检查前端/数据库并按顺序关闭资源 |
| `_register_api_routes(application)` | 创建聚合路由，统一 `/api` 前缀和公共错误 Schema，按顺序注册 health 与 hello        |
| `_configure_openapi(application)`   | 在该应用的 OpenAPI 中补充公开的 ClientSettings Schema                              |
| `_mount_frontend(application)`      | 读取是否托管前端，按需挂载 FrontendFiles，位于 API 注册之后                        |

config.py 导出固定的 lazy_proxy 属性读取入口，get_settings() 缓存真实模型，bind_settings() 仅改变内部绑定，不替换公开代理。CLI 严格加载并绑定 --config 所选真实实例后再执行，运行期间不重绑；测试在资源关闭后恢复原缓存，包括未加载状态。导入和 repr 不读取 TOML，真实类型与序列化操作使用 getter 或 loader 返回的对象，详见[配置访问](configuration.md#python-配置访问)。临时迁移仅传数据库路径，不改变配置绑定。Session 工厂与 SDK provider 的生命周期作用域不变，不经 app.state 传递；应用构建和 OpenAPI 导出不创建真实 provider、Session 工厂、数据库连接或日志，也不要求前端产物。关闭顺序仍为清除 Session 工厂、await 引擎释放、解锁、清除并关闭 SDK provider、等待日志。

SQLite 使用本机文件系统，实际库版本至少为 3.51.3。数据库适配保持 app/infra/database.py 单模块，分离私有的目标路径校验、SQLite 连接初始化及显式 BEGIN 回调，create_database_engine() 负责引擎装配并仅为当前引擎注册事件。模块导入不创建引擎或 Session 工厂，不注册全局引擎监听；不引入多数据库分支、DAO、审计或软删除层。同进程只允许一个活跃的 Session 工厂作用域，get_session() 不接收 Request，通过模块工厂创建独占 Session；未初始化、关闭后或重复初始化均明确报错，事务仍由业务边界控制，细节见[数据库调用约定](database.md#异步数据库调用约定)。连接启用外键、有限锁等待和显式 BEGIN；日志模式、持久化级别和池容量仍取配置，正常连接拒绝隐式建库。WAL 保留单写入者约束，异步驱动不会将 SQLite 变成多写入者数据库。

SQLite 完整性基线的依据见[数据库指南](database.md#sqlite-版本要求)；模型索引与约束命名见[模型约束约定](database.md#模型约束与命名)。

初始迁移仅建立 Alembic 版本记录。建库与升级必须显式执行维护命令，正常启动不运行迁移或 `create_all()`。Alembic 的同步命令入口管理事件循环，通过 `AsyncConnection.run_sync()` 执行 DDL 桥接，不另建同步运行时引擎。已有数据的结构变更必须审查迁移，必要时使用 SQLite batch migration。

迁移代码集中在 backend/migrations/：operations.py 管理配置、源码 head 和显式升级；env.py 要求明确的绝对 database_path 再创建引擎，缺失时报错；development.py 用导入的 settings 在独占临时目录确定目标并重放、生成和检查，不派生或切换配置。运行时通过 operations 查询版本，operations 不反向依赖引擎。开发命令不连接日常库，应用升级仍须显式执行。

生成、审查、旧数据回归、迁移脚本能力及恢复边界统一见[数据库指南](database.md#迁移生成审查与验证)。测试中真实历史重放与合成机制验证分开，baseline 的空表断言只针对 `0001_baseline`。

应用 lifespan 与离线升级持有同一个数据库文件锁，防止相同数据库的重复服务或迁移并发；启动时先检查数据库存在，关闭连接后释放锁。维护前直接执行 `stop`，或在前台服务终端按 Ctrl+C，并确认清理完成；维护 CLI 仍需指定目标数据库的完整配置。锁路径从实际数据库路径派生，例如 `.data/app.sqlite3.lock`，文件可保留，运行期间不删除；该机制只约束使用它的本机进程，其他数据库使用者也必须先停止。

maintenance/backup.py 的 DatabaseBackup 执行时读取 settings，异步创建并校验独占快照；CLI 绑定配置后直接实例化备份或迁移类，不经过空工厂。备份对象不管理服务状态，恢复与版本匹配步骤见[数据库指南](database.md#数据库与备份)。

## 前端与接口契约

TanStack Query 管理服务端状态，`api/client.ts` 负责请求超时、取消和错误解析；`useWelcome` 组合 Hello 与健康检查，页面和连接组件呈现加载、失败、成功及重试状态。保持现有 Hello 视觉设计，支持键盘操作和窄屏使用，不增加全局业务状态库。

| Method / 路径                      | 契约                                  |
| ---------------------------------- | ------------------------------------- |
| `GET /api/v1/hello`                | 固定返回 `{"message": "Hello World"}` |
| `GET /api/health`                  | 检查服务和真实 SQLite 连接            |
| `/`、`/welcome`                    | Hello 欢迎页，可直接访问和刷新        |
| `/docs`、`/redoc`、`/openapi.json` | 文档与 Schema；开关和路径来自配置     |

成功响应直接返回 Schema；错误统一为 `code`、`message`、`details`、`trace_id`。未预期的内部细节进入日志，不返回给浏览器。未知 API 和缺失静态资源返回真实 404；仅页面导航可回退到 SPA HTML。查询按配置有限重试，写请求重试次数必须显式配置为 0。

FastAPI 原生 telemetry 通过公共 TracerProvider/Tracer API 适配入口使用 lifespan 作用域内的本地 SDK provider。适配入口只保存插桩元数据，FastAPI 即使缓存 tracer，后续每次 span 操作也会读取当前作用域的真实 provider；未初始化或已关闭时报错，不自动创建资源，不修改 FastAPI 私有属性或设置全局 provider。官方 W3C propagator 解析 traceparent：有效时继承 trace ID，缺失或无效时由 SDK 创建新 trace ID；每次请求创建新的服务端 span ID，沿用 SDK 随机 ID 生成器。解析行为仍由官方库决定，1.45.1 容忍头部两端空白，对重复请求头取首个值，不叠加自定义规则。[FastAPI 原生 telemetry](https://fastapi.tiangolo.com/advanced/opentelemetry/)

采样器固定为 `ALWAYS_OFF`。原生请求 span 使用不记录数据的上下文；metrics、OTel logs、operation_spans、SDK 内部指标与自动导出全部关闭，provider 不注册采集/导出 processor 或 exporter。即使上游标记为采样，也不会启用本地记录。业务项目如需采集，应另行设计配置和数据处理边界。

请求中间件读取当前有效 span 的 trace ID，并写入 `request.state.trace_id`、Loguru 上下文和错误体。官方 propagator 在请求入口将本次服务端上下文序列化为 `traceparent`，保存在请求状态，并用于正常和错误响应头。格式为 `00-<32 位 trace ID>-<16 位服务端 span ID>-<2 位 flags>`；服务端 span ID 与上游 parent ID 不同，flags 采用 SDK 当前值，采样位关闭。只返回 `traceparent`，不额外回传 `tracestate`。

500 处理器从请求状态恢复日志上下文和保存的响应头，保证中间件退出后仍关联本次服务端 span。同一链路的请求可以共享 trace ID；不再提供 `X-Trace-ID`、`request_id` 或 `X-Request-ID`。错误响应继续保留 no-store 和 nosniff，HTTP 异常仅透传 Allow、WWW-Authenticate、Retry-After 协议头。前端错误对象继续从错误体读取 `trace_id`，不依赖自定义响应头。

app/telemetry/ 的包入口只导出轻量 getter 和作用域，不提前加载配置、适配器或 SDK，保证 app 包入口先清理外部环境。environment.py 在构建和 provider 初始化阶段桥接白名单，provider.py 在作用域内创建 SDK 资源并安装官方传播器，adapter.py 负责公共 API 转发。日志初始化失败时没有真实 provider，创建失败仍等待日志，正常、异常和取消退出均由作用域清除并关闭已创建 provider。具体开关、白名单和进程边界见[配置约定](configuration.md#遥测上下文与环境隔离)。

接口类型链路为 Pydantic Schema → CLI 导出 OpenAPI → openapi-typescript → `api.generated.d.ts`。生成文件由生成器维护，Prettier 忽略它；检查模式发现过期类型时失败而不改写文件。编译期类型不能代替服务端运行时校验。后续业务的时间按 UTC 保存和输出，API 使用带时区的 ISO 8601。

## 配置、访问与进程边界

Uvicorn 启动参数固定在 service.sh：127.0.0.1:18001、关闭期限10秒、Keep-Alive5秒、backlog2048、单worker、并发不限，不读取 .env 或环境覆盖。其余参数仍来自 configs/app.toml，通过 --config 另选；所有字段必填，保留严格校验、零值语义和路径保护，见[配置约定](configuration.md)。创建器和隔离测试只改生成副本或临时副本的端口常量。

service.sh 通过 entrypoints.cli 的 export-service-settings 获取 TOML 来源、日志和等待预算，自行计算固定地址、登记实例并 exec Uvicorn CLI。Shell 与 Uvicorn 的 PID/启动时间不变，不 eval 数据；entrypoints/api.py 只保留 create_app 导入和 app = create_app()，不再保留 service.py 或 create_service_app 包装。应用工厂读取 config.settings 构建应用，不初始化日志或登记实例；lifespan 先配置日志，再检查和管理运行资源，请求依赖的资源归属不变。

固定 .run 只保存 instance.json、console.log 及原子更新期间的 instance.json.pending，不创建 control.lock 或 run.lock。五个命令不提供并发互斥，已有实例检查只方便串行使用；运维负责避免并发启停和非预期多实例。保留记录的 0600、文件所有者和符号链接保护。数据库维护锁保持原机制，与服务管理无锁的选择分开。

start/run 先核对已有实例，有实例不读取新配置。status/stop 只消费记录中的实际地址、身份和停止期限，不依赖当前配置。restart 预校验目标文件，停止成功后启动，不提供命令锁或配置冻结；运维负责串行调用。默认读取 configs/app.toml；预校验后的文件变化仍可能导致停服后启动失败。后台启动成功要求身份匹配、监听归属和健康 HTTP/JSON 通过。

记录格式 3 只以 PID 和系统启动时间识别进程，另存 TOML 来源、URL、日志与停止期限；删除 UID、完整命令和项目路径字段及比对。系统启动时间固定从 C/UTC 的 ps 结果读取，僵尸进程视为已退出，身份不匹配拒绝发信号。停止在核对后发 SIGINT，并等待同一 PID/启动时间的进程退出，即使记录被删除也不能提前成功；进程查询失败返回错误，保留匹配记录，不能据此判定目标退出；超时不强杀，失败不继续重启。检查与发信号间仍有 PID 复用竞态。正常退出可留下记录，后续按进程实际状态判定失效，stop 在退出后清理匹配记录，新登记原子替换旧记录；旧格式记录拒绝控制，切换前使用旧版代码停服。

服务管理没有并发锁，记录丢失或并发调用都可能导致重复启动，不能靠记录检查提供互斥保证，由运维控制。数据库维护锁只约束同一数据库，不替代项目级实例发现。这是当前明确接受的本地运行分工。

管理命令依赖 ps、lsof、curl。管理成功 0、status 已停止 3、参数错误 2、其他错误 1，管理命令中断仍为 130/143。前台 run 透传 Uvicorn 原生退出结果，不统一转换信号退出码；当前锁定版本在服务运行后接收 SIGINT 可返回 0，SIGTERM 按信号结束，lifespan 启动失败可返回 3。服务工厂不安装进程信号处理器或 atexit 钩子，不接管重复信号，也不额外保证最后几条 Uvicorn 日志排空。后台管理仍等待进程退出，超时不强杀，失败不继续重启，查询中断不停止既有实例。

日志由 lifespan 在 try 内开始处统一配置，再创建真实 provider 和检查前端/数据库；日志初始化失败时不创建 provider，所有退出路径仍等待日志。导入 api.py、应用构建和 OpenAPI 导出均不创建日志。Uvicorn 进入 lifespan 前的启动消息保留原生控制台输出，初始化后的日志使用 Loguru，后台控制台追加到 .run/console.log。数据库、provider 和应用阶段日志清理顺序不变；不额外注册进程级排空钩子，不保证 Uvicorn 最后几条队列日志全部写入。日志取 TOML logging，不注册开机自启或崩溃重拉。

E2E 由 Playwright 向自有服务进程组发送 SIGINT，使用 Uvicorn 原生 Ctrl+C 路径并等待退出；不再依赖自定义信号转换或末尾日志保证。运行器中断或超时时也先向自有进程组发送 SIGINT，保留既有等待期限及仅针对自有临时进程的最终 SIGKILL 回收。服务控制命令和后端测试辅助器超时不强杀；E2E 超时必须失败并保留诊断，强制回收不证明应用资源清理完成。

app/infra/logging.py 的 configure_logging() 读取 settings.logging，分组局部变量命名 logging_settings；std_logging 与 Loguru logger 保持区分。RequestMiddleware 从导入的 settings 读取主机、Origin 和请求日志开关。日志仍在 lifespan 初始化，仅日志适配器测试直接调用该函数；队列和敏感信息保护不变，不增加进程级排空。

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
