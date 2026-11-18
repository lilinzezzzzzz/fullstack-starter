# 后端与服务入口规则

适用于 `backend/` 及项目根的 `entrypoints/service.sh`；同时遵循[根目录规则](../AGENTS.md)。修改迁移代码前再读取 [migrations/AGENTS.md](migrations/AGENTS.md)。

## 职责与依赖

- `app/routers/` 负责 HTTP 参数、依赖声明、调用与响应映射，不执行数据库写入；`app/services/` 负责业务规则、查询与写事务；`app/models/` 定义持久化结构；`app/schemas/` 定义 Pydantic I/O Schema。
- Service 使用类，通过构造参数注入依赖。业务类不处理 FastAPI Request/Depends、不构造 I/O Schema 或基础设施；各自的模块级 `new_*_service` 工厂与类同文件，可用 Request/Depends 组装依赖。Router 声明 Depends，CLI 显式组装。不要把模块允许使用 FastAPI 误解为业务类允许依赖框架。
- 只有无状态且不持有请求、Session 或可变配置的服务才可跨请求缓存。复杂查询出现实际复用后再提取 DAO，不预设通用 CRUD、Service 或 Repository 基类。
- app/maintenance 放维护基础设施，entrypoints/cli.py 处理维护参数与事件循环边界，并通过 export-service-settings 导出 TOML 来源、日志和等待期限。service.sh 直接实现五个管理命令，Uvicorn 参数固定在脚本，不读取 .env 或保留 Python 控制器。api.py 只保留 create_app 导入和 app = create_app()，不初始化日志或保留 create_service_app 包装；应用不反向依赖入口、不操作进程或状态文件，运维负责串行调用。service.py 和 server_environment.py 已删除。
- `app/utils/` 的路径策略和数据库锁保持标准库依赖与轻量包入口，由调用方传参，不反向依赖 Settings、Service 或工具；项目创建器需要在无应用依赖时加载路径策略。
- `app/infra/` 提供数据库、日志、静态托管和通用 HTTP 适配，可依赖 Settings、I/O Schema 与框架，但不反向依赖 Router、业务 Service 或应用工厂。`middleware.py` 提供 ASGI 请求处理，`errors.py` 提供标准错误响应和异常处理器，应用工厂保持原注册顺序并使用 `errors.register_error_handlers(application)`。`frontend.py` 提供产物检查与文件服务，挂载及 API 优先顺序由应用工厂管理。包入口保持轻量，不自动导入实现、注册组件或创建资源；应用生命周期和可执行入口负责装配、关闭。

## 数据库与生命周期

- 使用 SQLAlchemy 2.0 AsyncEngine、async_sessionmaker 和 aiosqlite；每个请求或任务独占 AsyncSession，禁止并发共享。数据库 I/O 使用 async/await，避免关系懒加载造成隐式 I/O；纯计算可保留同步函数。
- 数据库适配保持单文件 app/infra/database.py，只支持 SQLite。路径解析校验、SQLite 连接初始化和显式 BEGIN 使用同文件私有函数，create_database_engine() 组装 URI、池参数和当前引擎的事件监听；模块导入时不创建引擎、Session 工厂、连接或注册全局引擎事件。数据库模块用空初始状态持有进程内 Session 工厂，lifespan 在版本检查后进入 session_factory_scope(engine)，退出时先清除工厂，再关闭引擎并释放维护锁。重复初始化报错且不影响原作用域，未初始化或已关闭时 get_session() 明确报错，不自动创建资源；无参数请求依赖每次创建和关闭独占 Session，不自动提交事务。不引入通用 DAO、审计或软删除模型。
- Service 使用 `async with session.begin()` 管理写事务，成功提交，异常与取消回滚；保持连接外键、显式 BEGIN、有限锁等待和参数隐藏。SQLite 最低版本由 `app/infra/database.py` 的完整性基线约束，检查 Python 实际链接的库。
- 普通运行时模块顶部使用 from app.config import settings 导入固定代理，函数执行时读取 settings.xxx，不在顶部读取属性、计算配置常量或将其作为函数默认参数。create_app() 先桥接白名单，再向 FastAPI 注入无资源适配器并装配路由，API 先于 SPA。lifespan 管理日志、provider、前端检查和数据库，不经 app.state 传递配置或资源。关闭顺序仍为清除 Session 工厂、await 引擎释放、释放维护锁、清除并关闭 SDK provider、等待日志；运行期间不重绑，同进程仅一个活跃的 provider 和 Session 工厂作用域。
- 正常连接不静默创建缺失数据库；建库与升级走显式维护 CLI。运行服务和升级持有同一数据库文件锁，连接关闭后再释放。
- 备份使用 aiosqlite Backup API、独占新文件、完整性与迁移版本校验，不覆盖已有快照。取消时等待已提交的复制结束，关闭连接、清理未返回快照并继续传播取消；不能只复制运行中的 SQLite 主文件。

## 配置、日志与 telemetry

- Settings 保持严格 TOML 校验与全部必填，Uvicorn 参数固定在 Shell。config.py 用标准库 lazy_proxy 导出固定 settings 代理，创建、导入和 repr 不读配置；首次属性取值由 get_settings() 按 APP_CONFIG_FILE 或固定入口加载真实 Settings 并缓存，环境变量只选择文件。bind_settings(real_settings) 绑定已校验对象并返回旧缓存，None 恢复未加载状态；不接受代理或字典，不替换公开代理。CLI 先 load_settings(path) 严格校验 --config，再绑定并执行；loader 不读写缓存。测试通过绑定接口选择配置，自动 fixture 保存并在资源关闭后恢复原缓存，包括空状态，不直接操作私有缓存或替换代理。真实类型、身份与序列化操作使用 getter 或 loader 的真实对象；代理只转发属性读取，不提供赋值、删除或特殊协议透明性。各分组约束、未知字段拒绝、零值语义和路径保护不变。
- 中间件、日志、前端、数据库、备份和迁移工具直接导入所需 settings、常量和校验函数，不保留 config.settings 别名或转传 Settings；分组可用 logging_settings、telemetry 命名。CLI 和测试继续使用配置模块的 loader/getter/bind 接口。数据库直接导入 PROJECT_ROOT 和 validate_filename；隔离测试同时替换配置模块与数据库使用处的路径基准，不依赖导出模块属性更新传播。路径保护、目标目录创建和临时迁移隔离不变，在线 Alembic 缺少路径仍报错。migration_heads() 独立读取源码历史，路径和锁工具只依赖标准库。
- `app/__init__.py` 在第三方导入前清除继承的 `OTEL_*` / `FASTAPI_OTEL_*`；telemetry 包入口保持轻量，避免提前导入配置、FastAPI、Pydantic 或 SDK。
- telemetry/environment.py 与 provider.py 的轻量入口继续在函数内 from app.config import settings，延迟导入配置模块和 Pydantic，保证先清理外部环境；不能因代理不读 TOML 就将此导入提到顶部。白名单只在构建和初始化阶段桥接，真实 SDK 资源只在 tracer_provider_scope() 中创建，异常和取消也清除并关闭，getter 在未初始化或关闭后报错。adapter.py 仅使用 OpenTelemetry 公共接口转发，兼容 FastAPI 缓存与重复生命周期，不修改框架私有属性或替换全局 provider。
- 原生 telemetry 只维护上下文：`ALWAYS_OFF`，metrics、OTel logs、operation spans、内部指标与自动导出关闭，不注册采集/导出 processor 或 exporter。使用官方 propagator 解析与注入 `traceparent`，不自行生成 UUID trace ID 或叠加解析规则。
- 导入 api.py、构建应用和导出 OpenAPI 只创建无资源适配入口，不创建真实 SDK provider 或 Session 工厂，不连接数据库、不创建日志或要求前端产物；OpenAPI CLI 不再执行 provider.shutdown()。日志初始化失败时尚未创建 provider；provider 创建失败仍等待日志，其他启动失败由作用域关闭已创建的 provider。重复进入 provider 作用域报错且不影响原作用域，关闭失败仍清除模块引用。
- Loguru 保持 `enqueue=True`、`backtrace=False`、`diagnose=False`，lifespan 初始化后将标准 Uvicorn 日志统一桥接；此前的原生启动消息保留控制台输出。固定策略集中在 `LoggingSettings` 的 `ClassVar`，不作为 TOML 字段或配置导出项；派生属性只为调用方转换值，边界见[配置约定](../docs/configuration.md#已收拢的运行参数)。`infra/logging.py` 使用 `std_logging` 引用标准库模块，与 Loguru 的 `logger` 实例区分。
- lifespan 最先使用进程配置 settings.logging 初始化 Loguru，再初始化 provider 并检查前端和数据库，所有退出路径均等待应用阶段日志。实例登记由 Shell 在 exec 前完成，停止交给 Uvicorn 原生处理，不接管信号、转换退出码或额外排空末尾日志。普通 application 模块导入不读取共享 settings，OpenAPI 导出只绑定配置并构建应用，不进入 lifespan。具体边界见[根规则](../AGENTS.md#服务管理共同契约)与[设计](../docs/design.md#配置访问与进程边界)。

## 验证

以下是可用检查命令，按[根规则的验证策略](../AGENTS.md#工具与验证)从项目根定向选择，不要求每轮执行完整 pytest；完整命令维护在 [README](../README.md#接口类型与验证)。服务管理脚本通常先验证隔离启停、身份、信号与超时，启动链路完成后再按具体风险选择一次整体浏览器验收。

```bash
uv run --directory backend ruff check --config pyproject.toml . ../scripts/create_project.py
uv run --directory backend ruff format --check --config pyproject.toml . ../scripts/create_project.py
uv run --directory backend pytest
```

- 优先复用 `tests/helpers.py` 的 `settings_for` 和 `tests/conftest.py`；测试配置必须完整，数据库、日志与构建产物使用临时路径；服务测试必须从独立临时项目副本调用真实入口，隔离固定 `.run/`，不增加用于测试绕过项目单实例约束的配置或环境变量。
- API/错误/静态回退、配置/日志、telemetry/traceparent、异步数据库、迁移、服务与项目创建各有对应 `test_*.py`，按实际影响选择，不用历史测试总数判断通过。
- `integration` 测试启动自有本机进程，需要监听与信号权限；受限时可执行 `uv run --directory backend pytest -m 'not integration'`，但必须报告未执行真实启停，不能声称完整回归通过。
- 改动导入、应用工厂或 telemetry 时，覆盖无数据库/无前端产物的导入及 OpenAPI 导出、冲突环境隔离和资源关闭；OpenAPI Schema 变化还需生成并检查前端类型。

## 服务管理共同契约

共同契约统一维护在[根目录规则](../AGENTS.md#服务管理共同契约)，包括唯一 service.sh 入口、五个命令、原生环境入口、运维串行管理、身份检查及退出边界。本目录不另复制协议，后端实现和测试同时满足根契约与上面的资源归属要求。
