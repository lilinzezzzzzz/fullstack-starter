# 后端规则

适用于 `backend/`；同时遵循[根目录规则](../AGENTS.md)。修改迁移代码前再读取 [migrations/AGENTS.md](migrations/AGENTS.md)。

## 职责与依赖

- `app/routers/` 负责 HTTP 参数、依赖声明、调用与响应映射，不执行数据库写入；`app/services/` 负责业务规则、查询与写事务；`app/models/` 定义持久化结构；`app/schemas/` 定义 Pydantic I/O Schema。
- Service 使用类，通过构造参数注入依赖。业务类不处理 FastAPI Request/Depends、不构造 I/O Schema 或基础设施；各自的模块级 `new_*_service` 工厂与类同文件，可用 Request/Depends 组装依赖。Router 声明 Depends，CLI 显式组装。不要把模块允许使用 FastAPI 误解为业务类允许依赖框架。
- 只有无状态且不持有请求、Session 或可变配置的服务才可跨请求缓存。复杂查询出现实际复用后再提取 DAO，不预设通用 CRUD、Service 或 Repository 基类。
- `app/maintenance/` 放 CLI 专属维护基础设施；`entrypoints/cli.py` 处理维护参数和事件循环边界；`entrypoints/` 集中放置后端可执行入口，`service.sh` 通过 uv 定位预装解释器后直接 exec Python，不保留 uv 父进程转发信号；同目录的 `service.py` 解析五个显式子命令并装配单 worker Uvicorn，`service_control.py` 管理实例登记、文件锁与仅监听回环地址的认证控制通道。`run` 与后台进程共用运行路径和固定的项目根 `.run/`，不按配置或数据库划分实例，不增加业务 API 或外部进程管理器。业务模块不反向依赖可执行入口或工程工具。
- `app/utils/` 的路径策略和数据库锁保持标准库依赖与轻量包入口，由调用方传参，不反向依赖 Settings、Service 或工具；项目创建器需要在无应用依赖时加载路径策略。
- `app/infra/` 提供数据库、日志、静态托管和通用 HTTP 适配，可依赖 Settings、I/O Schema 与框架，但不反向依赖 Router、业务 Service 或应用工厂。`middleware.py` 提供 ASGI 请求处理，`errors.py` 提供标准错误响应和异常处理器，应用工厂保持原注册顺序并使用 `errors.register_error_handlers(application)`。`frontend.py` 提供产物检查与文件服务，挂载及 API 优先顺序由应用工厂管理。包入口保持轻量，不自动导入实现、注册组件或创建资源；应用生命周期和可执行入口负责装配、关闭。

## 数据库与生命周期

- 使用 SQLAlchemy 2.0 AsyncEngine、async_sessionmaker 和 aiosqlite；每个请求或任务独占 AsyncSession，禁止并发共享。数据库 I/O 使用 async/await，避免关系懒加载造成隐式 I/O；纯计算可保留同步函数。
- Service 使用 `async with session.begin()` 管理写事务，成功提交，异常与取消回滚；保持连接外键、显式 BEGIN、有限锁等待和参数隐藏。SQLite 最低版本由 `app/infra/database.py` 的完整性基线约束，检查 Python 实际链接的库。
- `app/application.py` 的 `create_app(settings)` 显式接收配置，构造 FastAPI 与本地 provider，再按顺序装配中间件、异常处理、API 路由、OpenAPI 与前端；具体 HTTP 处理保留在 `routers/`，API 注册先于 SPA 挂载。同文件的模块级 lifespan 从当前应用状态读取依赖，管理数据库版本/前端检查与运行资源，保持先 await 引擎释放、再解锁、再关闭 provider 和等待日志的顺序。`app.state` 是框架装配与依赖适配边界，业务类通过注入获取依赖；配置、数据库与 provider 绑定当前应用，Loguru 沿用现有进程级配置。
- 正常连接不静默创建缺失数据库；建库与升级走显式维护 CLI。运行服务和升级持有同一数据库文件锁，连接关闭后再释放。
- 备份使用 aiosqlite Backup API、独占新文件、完整性与迁移版本校验，不覆盖已有快照。取消时等待已提交的复制结束，关闭连接、清理未返回快照并继续传播取消；不能只复制运行中的 SQLite 主文件。

## 配置、日志与 telemetry

- Settings 保持严格校验与全部必填；协议和安全不变量固定在代码，不增加绕过检查的配置项。路径安全规则复用 `app/utils/path_safety.py`，处理符号链接、大小写别名和双向目录重叠。
- `app/__init__.py` 在第三方导入前清除继承的 `OTEL_*` / `FASTAPI_OTEL_*`；telemetry 包入口保持轻量，避免提前导入配置、FastAPI、Pydantic 或 SDK。
- `app/telemetry/environment.py` 仅在应用构建时桥接配置文档中的 TOML 白名单，请求期间不改环境；`provider.py` 显式创建本地 SDK provider、Resource 和 SpanLimits，不替换全局 tracer/meter/logger provider。
- 原生 telemetry 只维护上下文：`ALWAYS_OFF`，metrics、OTel logs、operation spans、内部指标与自动导出关闭，不注册采集/导出 processor 或 exporter。使用官方 propagator 解析与注入 `traceparent`，不自行生成 UUID trace ID 或叠加解析规则。
- lifespan 在正常退出和启动失败时关闭 provider；OpenAPI CLI 没有 lifespan，必须显式关闭 provider。
- Loguru 保持 `enqueue=True`、`backtrace=False`、`diagnose=False`，标准日志与 Uvicorn 统一桥接。固定策略集中在 `LoggingSettings` 的 `ClassVar`，不作为 TOML 字段或配置导出项；派生属性只为调用方转换值，边界见[配置约定](../docs/configuration.md#已收拢的运行参数)。`infra/logging.py` 使用 `std_logging` 引用标准库模块，与 Loguru 的 `logger` 实例区分。
- 前台 Ctrl+C 与管理命令的 SIGINT 关闭均由 Uvicorn 处理；lifespan 清理资源并等待日志，服务入口再排空最后的关闭日志，随后移除实例记录并释放实例锁。Uvicorn 返回后的末尾清理临时忽略重复 SIGINT，结束后恢复处理器，不改变运行期间的原生信号行为。`.run/control.lock` 防止启停并发，`.run/run.lock` 覆盖完整运行及日志清理；数据库操作锁仍由 lifespan 与迁移共享并保留在数据库旁。`.run/instance.json` 原子保存 PID、UTC 启动时间、完整 Python 启动命令、配置路径及控制身份，后台控制台写入 `.run/console.log`，应用日志仍取 `[logging]`。实例凭据文件权限为 0600，不进入 Git、日志或命令行；凭据、PID、配置身份不匹配时不发信号。停止超时保留实例，不自动强杀，restart 不继续启动；其他信号及强制终止的限制见[进程约定](../docs/design.md#配置访问与进程边界)。错误体、请求日志和响应 trace 上下文保持关联，内部异常细节仅进入日志。

## 验证

以下命令从项目根目录运行，按影响范围选择；完整命令维护在 [README](../README.md#接口类型与验证)。

```bash
uv run --directory backend ruff check --config pyproject.toml . ../scripts/create_project.py
uv run --directory backend ruff format --check --config pyproject.toml . ../scripts/create_project.py
uv run --directory backend pytest
```

- 优先复用 `tests/helpers.py` 的 `settings_for` 和 `tests/conftest.py`；测试配置必须完整，数据库、日志与构建产物使用临时路径；服务测试必须从独立临时项目副本调用真实入口，隔离固定 `.run/`，不增加用于测试绕过项目单实例约束的配置或环境变量。
- API/错误/静态回退、配置/日志、telemetry/traceparent、异步数据库、迁移、服务与项目创建各有对应 `test_*.py`，按实际影响选择，不用历史测试总数判断通过。
- `integration` 测试启动自有本机进程，需要监听与信号权限；受限时可执行 `uv run --directory backend pytest -m 'not integration'`，但必须报告未执行真实启停，不能声称完整回归通过。
- 改动导入、应用工厂或 telemetry 时，覆盖无数据库/无前端产物的导入及 OpenAPI 导出、冲突环境隔离和资源关闭；API 或公开配置 Schema 变化还需生成并检查前端类型。
