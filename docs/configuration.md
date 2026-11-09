# 配置审查与使用约定

## 结论与格式选择

本项目的应用配置入口为 [configs/app.toml](../configs/app.toml)。当前有 **100 个叶子配置项**，所有字段和分组都必须显式提供。缺项、未知项、错误类型或无效数值直接报错，不由代码、环境变量、`.env` 或旧 JSON 文件补齐。

JSON 是可靠的机器交换格式，适合 API、生成数据和工具元信息。这里的配置主要由人维护，字段增加后需要分组和注释，因此选择 TOML。它不是对所有项目都最优，而是更适合当前 Python 主导、前后端同仓库的小型脚手架。[TOML 规范](https://toml.io/en/)

Python 3.14 使用原生 `tomllib` 解析 TOML 1.0，再由 Pydantic 统一校验；标准库不提供写入能力，测试使用开发依赖 `tomli-w`。Node 端测试使用 `smol-toml` 写入临时 TOML，实际应用值仍通过 Python 校验后取得。[Python tomllib 文档](https://docs.python.org/3.14/library/tomllib.html)

`package.json`、`tsconfig.json`、API JSON 和页面测试运行元信息仍遵循各工具或协议的原生格式，它们不是旧的应用 JSON 配置入口。

## 已收拢的运行参数

| 分组 | 必填字段 | 使用位置 |
| --- | --- | --- |
| 根配置 | `data_dir`, `database_filename`, `backup_directory`, `frontend_dir`, `serve_frontend`, `frontend_clean_output`, `sqlite_timeout_seconds`, `allowed_hosts`, `allowed_origins` | 数据库、备份、前端输出和本机访问边界 |
| `application` | `title`, `version`, `docs_enabled`, `redoc_enabled`, `openapi_enabled`, `docs_path`, `redoc_path`, `openapi_path` | FastAPI 标题、版本、文档路由与前端应用标识；不影响固定的 Hello 欢迎语 |
| `server` | `host`, `port`, `workers`, `graceful_shutdown_seconds`, `keep_alive_seconds`, `backlog`, `concurrency_limit` | 单 worker 启动、优雅关闭、Keep-Alive、backlog、并发上限 |
| `database` | `journal_mode`, `synchronous`, `pool_size`, `max_overflow`, `pool_timeout_seconds` | SQLite 日志与持久化模式、连接池容量和等待时间 |
| `logging` | `directory`, `filename`, `level`, `format`, `rotation`, `retention_days`, `compression`, `serialize`, `console`, `request_logging` | Loguru 文件、等级、格式、轮转、保留、压缩、序列化与访问日志 |
| `telemetry` | `tracing`, `metrics`, `logs`, `operation_spans`, `auto_configure`, `sampler`, `id_generator`, `sdk_disabled`, `internal_metrics_enabled`, `shutdown_on_exit`, `context`, `propagators`, `known_methods` | 原生请求上下文、SDK 生命周期、传播协议与受控环境桥接 |
| `telemetry.span_limits` | `max_attributes`, `max_events`, `max_links`, `max_span_attributes`, `max_event_attributes`, `max_link_attributes`, `max_attribute_length`, `max_span_attribute_length` | 显式传入全部八项 SDK SpanLimits；随附值均为 0 |
| `vite` | `host`, `port`, `proxy_target`, `strict_port`, `change_origin` | 开发服务器地址、端口、严格端口策略和代理行为 |
| `client` | `request_timeout_seconds`, `query_stale_seconds`, `query_cache_seconds`, `query_retry_attempts`, `query_retry_delay_seconds`, `retry_min_status`, `retry_network_errors`, `refetch_on_window_focus`, `refetch_on_mount`, `refetch_on_reconnect`, `mutation_retry_attempts`, `theme_primary_color`, `theme_border_radius`, `theme_font_size`, `theme_font_family` | 请求超时、查询缓存/重试/刷新、写重试约束、组件主题 |
| `testing` | `temporary_directory`, `host`, `termination_grace_seconds`, `command_timeout_seconds`, `keep_artifacts`, `browser`, `viewport_width`, `viewport_height`, `mobile_width`, `mobile_height`, `workers`, `retries`, `test_timeout_seconds`, `expect_timeout_seconds`, `action_timeout_seconds`, `navigation_timeout_seconds`, `trace`, `screenshot`, `fully_parallel`, `reporter` | 临时目录、进程预算、浏览器、视口、并行度、重试、超时和诊断产物 |

具体取值、单位与注释以主 TOML 文件为准。提供在文件里的数值是操作者选择的值，不是缺失时的默认值。

- `logging.retention_days = 0` 显式表示保留所有轮转日志。
- `server.concurrency_limit = 0` 显式表示不设置并发上限。
- `testing.action_timeout_seconds = 0` 显式关闭单动作超时。
- `false`、`0` 和空的允许列表会按其真实含义使用，不通过 `or`、`??` 或模型默认值替换。
- 浮点时间必须有限，不接受 `inf` 或 `nan`。

所有相对路径均相对于项目根目录，支持绝对路径。`data_dir`、数据库文件名、备份目录和日志目录独立配置。修改数据目录时也需核对备份目录。

随附配置使用 `.data/app.sqlite3` 保存数据库，使用 `.data/backups/` 保存备份；`.data/` 整体被 Git 忽略。相对路径的解析规则不因目录以点开头而改变。

服务改为前台运行，不再需要 `[service]` 分组及 `logging.bootstrap_filename`。旧版完整 TOML 应删除这些字段，未知字段仍明确失败，不做隐式兼容或合并。启动不接受后台控制子命令，停止使用 Ctrl+C。

应用 lifespan 与 `db-upgrade` 共用数据库旁的文件锁，例如 `.data/app.sqlite3.lock`，路径属于固定安全机制，不额外增加配置项。锁在关闭连接后或进程退出时释放，文件可以保留；运行期间不要删除。切换数据库路径或执行迁移前先停止服务；文件锁只约束使用同一机制的本机进程。

应用加载和项目生成共用 `backend/app/utils/path_safety.py`：运行路径不得包含受保护源码，也不得落入其中；保护范围含 `backend/`、`frontend/`、`entrypoints/`、`scripts/`、`configs/`、`docs/`、`.git/`、项目入口文件，以及遗留 `data/`、`.data/`、`logs/`、`.run/`、`.venv/`、`node_modules/` 和 Python 缓存目录。只有公开输出允许位于 `frontend/dist/` 子树；私有目录与公开输出不能双向重叠。路径解析符号链接并折叠大小写后检查，避免 macOS 大小写不敏感文件系统上的别名绕过。自动清空仍仅允许实际的 `frontend/dist`；通过符号链接指向该目录外部时不允许自动清空。

数据库文件、数据库锁和应用日志必须指向不同路径；同一目录下的文件名相同也会被拒绝。`data_dir`、`backup_directory` 和 `logging.directory` 还不得落入 `.venv/`、`node_modules/` 或 Python 缓存目录。

`testing.temporary_directory` 是创建独占子目录的父位置，允许 `/tmp` 这样的外部父目录，但不得直接使用项目根目录、源码或公开输出目录。E2E 强制使用本次临时目录中的构建、数据和日志，不复用日常产物。

迁移开发命令 `db-revision` 与 `db-check` 也使用这个父目录，始终清理本次临时子目录，不保留迁移数据库。命令先校验完整 TOML，再从其全部字段派生临时设置，将数据、备份、日志和前端输出限定到独占目录，并关闭前端托管与自动清空；派生结果再次通过 `Settings` 校验。数据库连接参数沿用所选 TOML，不增加配置字段或环境变量来源。强制资源隔离属于工具的固定安全边界，不能用配置关闭；`db-upgrade` 和 `db-backup` 仍操作 TOML 指定的应用数据库。操作步骤与迁移脚本能力边界见 [README](../README.md#迁移生成审查与验证)。

创建器保持标准库实现，只校验路径、源文件完整性和创建过程所需的关键字段；完整 Pydantic 字段、枚举和跨字段校验由生成项目的 `export-settings`、测试或首次启动执行。

随附 `.gitignore` 覆盖默认路径和常见产物；自定义任意文件名或目录后仍需检查 Git 忽略规则。生成器仅为新项目补入配置路径，不会修改原模板的 `.gitignore`。

## 前后端配置流

```text
configs/app.toml
       │ Python tomllib + Pydantic 完整校验
       ├── 前台 Uvicorn / 数据库 / Loguru
       └── 本地构建工具的受控 JSON 交换
                    ├── Vite 开发 / 构建参数
                    └── 浏览器白名单：client + 应用标题/版本
```

Vite 和 Playwright 使用同一配置校验器，不各自猜测字段或填默认值。构建前需要先安装后端依赖。浏览器包不包含数据目录、日志目录、完整服务设置或访问允许列表。

后端参数修改后重启；前端运行参数和组件主题在构建时注入，修改后重新构建再刷新。Vite 开发模式重新启动开发服务器即可读取新值。

`client.theme_*` 的范围是 Ant Design 组件。Hello 页面的品牌色、全局字体、页面排版和 CSS Modules 圆角属于固定视觉设计，不跟随组件主题参数；需要整体换肤时，应同步调整页面样式。

## 保留在代码中的固定契约

配置化的边界是可调运行参数。以下内容属于协议、完整性或安全规则，固定在代码中：

- API 业务路径、operation ID、HTTP 方法和响应/错误字段；界面状态文案和页面布局设计。
- 单 worker、严格端口、Uvicorn 信号与优雅关闭、服务与迁移互斥、启动失败的非零退出码与不按端口杀进程。
- SQLite 外键、显式事务、禁止跨并发任务共享 AsyncSession、参数隐藏、最低安全版本、只读连接与独占备份创建。
- 日志追加、UTF-8、关闭局部变量诊断和回溯扩展、单 worker 队列后台写入、退出时等待队列处理完成，以及标准日志桥接规则。
- 前端私有信息隔离、禁止通过配置绕过服务与迁移互斥或把源代码/数据目录作为公开构建输出。
- 源码/测试目录、生成文件名、测试用例数据、页面测试健康检查、CLI 交换缓冲上限与秒/毫秒换算。
- 第三方库尚未在本项目启用的功能，不额外制造配置项。

原生 telemetry 的采集关闭约束及 SDK 参数边界见下节，属于代码校验的固定能力范围。保留 SDK 并创建上下文不等于开启采集。

SQLite 统一要求 3.51.3+，是针对 [WAL-reset 数据损坏修复](https://sqlite.org/wal.html#walresetbug)的数据完整性基线。官方虽为 3.44.6、3.50.7 提供回补，本脚手架暂不按旧分支或发行版补丁建立例外；DELETE 模式也使用相同基线。检查方式与 Python 升级方向见 README。

错误响应的空详情列表、非请求日志的链路标识占位符和加载/错误文案属于协议或界面语义，不是配置缺失后的兜底参数。

## 遥测上下文与环境隔离

本项目只维护请求上下文，使用 FastAPI 原生 telemetry 和锁定的 OTel API/SDK 1.45.1。`telemetry.tracing = true`、`sdk_disabled = false` 保证 SDK 能创建有效上下文；采样器只接受 `always_off`，ID 生成器只接受 `random`，上下文实现只接受 `contextvars_context`，传播器只接受 `tracecontext`。其余六个布尔开关必须为 false：`metrics`、`logs`、`operation_spans`、`auto_configure`、`internal_metrics_enabled`、`shutdown_on_exit`。值违反范围时在配置校验阶段失败，不通过默认值修正。全部字段均必填。

`app` 包首先清除当前进程中继承的全部 `OTEL_*` / `FASTAPI_OTEL_*` 键，不记录其值。这样第三方模块在首次导入时不会消费外部 propagator、context、SDK 默认限制或导出配置。应用工厂在 SDK 导入和 provider 构建前再次清理，再用 TOML 值填充以下固定白名单；对 shell 和其他进程没有影响，请求期间不修改环境。

| SDK/FastAPI 环境入口 | TOML 字段 | 用途 |
| --- | --- | --- |
| `OTEL_SDK_DISABLED` | `telemetry.sdk_disabled` | 防止 SDK 被外部值变成 NoOp |
| `OTEL_PYTHON_SDK_INTERNAL_METRICS_ENABLED` | `telemetry.internal_metrics_enabled` | 禁用 SDK 自身指标 |
| `OTEL_PYTHON_CONTEXT` | `telemetry.context` | 明确支持的 contextvars 上下文实现 |
| `OTEL_PROPAGATORS` | `telemetry.propagators` | 明确 W3C tracecontext；同时用公开 API 安装该传播器，覆盖已有模块缓存 |
| `OTEL_INSTRUMENTATION_HTTP_KNOWN_METHODS` | `telemetry.known_methods` | FastAPI 原生 HTTP 方法归类，列表序列化为逗号分隔值 |
| `FASTAPI_OTEL_AUTO_CONFIGURE` | `telemetry.auto_configure` | 禁止自动初始化导出组件；FastAPI 参数也显式设为同一配置值 |

采样器、随机 ID 生成器和八项 SpanLimits 通过构造参数传入；Resource 的 `service.name`、`service.version` 分别取 `application.title`、`application.version`。Resource 直接构造，不调用自动探测环境的 `Resource.create()`。不设置全局 tracer/meter/logger provider；使用本地 tracer provider 和 NoOp meter provider，且不注册采集/导出 processor 或 exporter。应用 lifespan 管理 provider 关闭，OpenAPI CLI 在导出后显式关闭。

环境白名单只是第三方参数通道，不能作为第二个配置来源。未使用的 exporter、资源探测器和自动插桩入口保持不配置，外部同名前缀变量被丢弃。该入口管理整个单应用进程；如果宿主在导入 `app` 前已初始化第三方 OTel 实现，其先前副作用无法由应用撤销，运行入口应遵循本项目的 sh/CLI 顺序。

随附日志格式继续使用 `{extra[trace_id]}`，非请求日志使用 `-` 占位；正常响应和错误响应均返回当前服务端上下文的标准 `traceparent` 头，其中 trace ID 与错误体、500 日志一致。不返回 `X-Trace-ID`，也不原样回显上游 parent ID；不增加响应头名称配置开关。请求头缺失或无效时由 SDK 创建上下文，应用层没有 UUID 生成回退。trace ID 不再受 UUIDv7 格式约束，备份文件的 UUIDv7 命名不受影响。

## 引导入口与迁移

固定入口 `configs/app.toml` 和项目根目录定位是引导约定，不是运行字段的默认值。否则配置文件必须先告诉程序它自己的位置，会形成循环。`--config` 只用于显式选择另一个完整 TOML 文件；文件不存在就失败，不遍历其他文件或环境变量。

旧 `configs/app.json` 已移除，没有格式兼容回退。自定义旧 JSON 需要按主 TOML 的完整字段清单迁移；旧的本地私有 JSON 仍被 Git 忽略，防止误提交，但不会被加载。

当前项目仅使用单 worker。修改数据库路径前先按 Ctrl+C 停止服务；服务与维护命令使用同一个配置文件。

## 验证

- 逐一删除配置表或字段，验证所有项均不可省略。
- 验证错误类型、未知字段、非有限超时被拒绝，零值和 false 不被替换。
- 验证文件中的数据库池容量、日志模式、持久化模式、文档开关和应用标识实际生效。
- 回归前台启动、Ctrl+C 关闭、运行期间迁移互斥及 Chromium 欢迎页；测试全部使用临时 TOML、日志和数据库。

页面测试遵守 `testing.screenshot`，不强制绕过截图配置。验证还需检查前端公开白名单，确认构建 JavaScript 不包含私有存储或日志路径。历次实际检查见 [实现与验证记录](history.md)。

数据库执行栈固定为 SQLAlchemy 2.0 AsyncEngine/AsyncSession + aiosqlite，没有同步驱动回退开关；该技术选型属于架构契约，不额外制造配置项。`database.synchronous` 调整的是 SQLite 持久化级别。
