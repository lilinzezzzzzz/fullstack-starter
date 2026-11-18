# 配置审查与使用约定

## 结论与格式选择

应用配置入口为 [configs/app.toml](../configs/app.toml)，当前有95个 TOML 叶子配置项，全部字段和分组必填，拒绝缺项、未知项、错误类型和无效数值。Uvicorn 参数固定在 Shell 代码中，不读取 .env，也不由环境变量或旧 JSON 补值。

JSON 是可靠的机器交换格式，适合 API、生成数据和工具元信息。这里的配置主要由人维护，字段增加后需要分组和注释，因此选择 TOML。它不是对所有项目都最优，而是更适合当前 Python 主导、前后端同仓库的小型脚手架。[TOML 规范](https://toml.io/en/)

Python 3.14 使用原生 `tomllib` 解析 TOML 1.0，再由 Pydantic 统一校验；标准库不提供写入能力，测试使用开发依赖 `tomli-w`。Node 端测试使用 `smol-toml` 写入临时 TOML，实际应用值仍通过 Python 校验后取得。[Python tomllib 文档](https://docs.python.org/3.14/library/tomllib.html)

`package.json`、`tsconfig.json`、API JSON 和页面测试运行元信息仍遵循各工具或协议的原生格式，它们不是旧的应用 JSON 配置入口。

## Uvicorn CLI 固定参数

这些值在 entrypoints/service.sh 中写死，不再使用 .env、.env.example、--env-file 或 server_environment.py。host 和 port 在脚本内各有一个常量供启动和记录复用，其余参数直接写在 CLI 参数中。

| 参数         | 固定值                         |
| ------------ | ------------------------------ |
| host / port  | 127.0.0.1 / 18001              |
| 原生关闭期限 | 10秒                           |
| Keep-Alive   | 5秒                            |
| backlog      | 2048                           |
| workers      | 1                              |
| 并发上限     | 不限，不传 --limit-concurrency |

Shell 清除继承的 Uvicorn 参数环境变量，避免未传并发参数时被外部值覆盖。entrypoints.cli 的 export-service-settings 只导出 TOML 来源、日志和两个等待预算。Shell 使用实例记录中的停止预算等待目标进程退出。该预算独立于 Uvicorn 的优雅关闭等待。Shell 时限较短时，stop 可能先报超时，服务仍继续关闭。APP_CONFIG_FILE 仅传递 TOML 来源，api.py 只调用 application.create_app()，日志在 lifespan 开始时初始化。创建器 --port 重写生成副本的端口常量，测试和 E2E 只修改临时 Shell 副本的 host 和 port。

新实例启动前由同一配置校验器导出数据，已有匹配实例时不读取新配置。status/stop 完全由 Shell 处理，不启动 Python/uv，也不读取配置文件。服务不加锁，运维负责串行管理和配置变更，不保证跨进程配置冻结；普通应用导入和 OpenAPI 导出仍不导入服务入口。

## Python 配置访问

config.py 显式导出 settings = lazy_proxy(get_settings)，删除模块级 `__getattr__`。公开代理始终保留同一身份，只转发属性读取；创建、from-import 和 repr 均不调用 getter。首次实际读取属性时，get_settings() 按 APP_CONFIG_FILE 或固定 configs/app.toml 加载真实 Settings 并缓存，后续属性访问只复用当前缓存，不重复解析 TOML。APP_CONFIG_FILE 只选择来源文件，任何字段仍由所选 TOML 完整提供，不合并或回退。

代理本身不是 Settings，类型注解仅提供目标属性的静态提示；不转发属性赋值、删除、调用、迭代等协议，不保证类型判断、身份或直接序列化透明。不要用代理布尔值判断配置是否就绪，需要真实对象时调用 get_settings()；CLI JSON 导出使用 loader 返回的真实模型。getter 的读取和校验异常原样传播，不被代理吞掉。

普通运行时模块直接导入所需 settings、常量和校验函数，在函数中读取 settings.xxx；提前导入的代理在 CLI 或测试绑定后仍然有效。顶部导入不读取 TOML，但顶部属性取值、配置常量或函数默认实参会提前加载，应保留在执行阶段。CLI 和测试通过配置模块的 loader/getter/bind 接口管理真实对象；数据库直接导入 PROJECT_ROOT 和 validate_filename，隔离测试替换数据库使用处的根目录常量，同时保持配置加载的路径基准一致。运行期间配置不重绑，不提供切换或额外冻结/锁机制。应用构建和 OpenAPI 导出仍不创建 SDK/数据库运行资源，不要求前端产物。

日志由 lifespan 最先按 settings.logging 初始化，之后才创建真实 SDK provider 并检查前端/数据库；测试不提前配置日志。Uvicorn 进入 lifespan 前的启动消息走原生控制台，之后统一桥接到 Loguru，后台原生输出保存到 .run/console.log。日志初始化失败时尚未创建 provider；provider 初始化失败仍等待日志，其他退出由作用域清除并关闭已创建 provider，不增加进程退出钩子。

load_settings(path) 每次独立加载，不读写真实实例缓存；CLI 先用它严格校验 --config，再调用 bind_settings(real_settings)，保持公开代理不被替换。绑定接口只接受真实 Settings 或 None，返回旧缓存且不触发默认文件读取；None 表示未加载，下次实际取值才重新加载。CLI 校验失败时不绑定或执行操作，不回用缓存目标。其他模块已 from-import 的代理在绑定后同样读取所选配置。

测试在操作前通过 bind_settings() 选择真实实例，公共自动 fixture 保存并恢复原缓存，包括未加载状态，不直接访问私有缓存或用 monkeypatch 替换公开代理。资源关闭后才恢复或切换，不交错运行不同配置的应用。该代理仅用于配置访问，Session 工厂与 SDK provider 仍由各自作用域管理，不在 getter 中创建资源。

其他后端模块按配置用途处理，避免将操作目标和进程配置混在一起：

| 模块或接口                                                                                                   | 配置访问                                   | 边界                                                                 |
| ------------------------------------------------------------------------------------------------------------ | ------------------------------------------ | -------------------------------------------------------------------- |
| RequestMiddleware、configure_logging()、tracer_provider_scope()、configure_telemetry_environment()、前端挂载 | 执行时读取导入的 settings，不接收配置参数  | 真实 provider 只在作用域内创建；导入和 OpenAPI 导出不初始化 SDK 资源 |
| create_database_engine()、DatabaseBackup()、迁移操作与开发工具                                               | 执行时读取导入的 settings，不接收 Settings | 默认操作配置中的数据库；临时迁移只传 database_path，不改变配置绑定   |
| check_database_revision(engine)、migration_heads()                                                           | 不接收 Settings                            | 前者从实际引擎读取版本，后者只读取源码中的迁移历史                   |
| 路径安全与数据库文件锁工具                                                                                   | 显式路径等实际输入                         | 继续仅依赖标准库，供项目创建器独立使用                               |

telemetry 包参与 app 导入时的环境清理，provider 与环境桥接函数仍在函数内部 from app.config import settings。代理不读 TOML，但配置模块本身会导入 Pydantic，因此必须保留先清理外部环境、后加载配置和第三方库的顺序。其他运行时模块可在顶部导入代理，仅在执行时读取属性，不增加配置来源。

数据库路径覆盖是内部操作目标参数，不是 TOML 字段或第二个配置来源。create_database_engine(database_path=..., allow_create=True) 要求绝对路径，保留源码、公开输出、日志及 .run 等路径保护和符号链接/大小写别名检查，只创建目标父目录；连接池、超时、外键和 PRAGMA 仍取严格校验的进程配置。migration_config() 始终向 Alembic 上下文写入 database_path，在线 env.py 缺少有效路径时报错，不自行加载默认 TOML 或回退应用数据库。正常服务仍禁止隐式创建缺失数据库。

分组自己的约束由对应模型校验：ApplicationSettings 检查文档开关关系，TelemetrySettings 检查上下文模式；根 Settings 保留跨分组的运行路径安全检查。所有字段名称、必填性、类型约束和 TOML 取值保持原有契约。

## 已收拢的运行参数

| 分组                    | 必填字段                                                                                                                                                                                                                                                                                                                                                                      | 使用位置                                                              |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| 根配置                  | `data_dir`, `database_filename`, `backup_directory`, `frontend_dir`, `serve_frontend`, `frontend_clean_output`, `sqlite_timeout_seconds`, `allowed_hosts`, `allowed_origins`                                                                                                                                                                                                  | 数据库、备份、前端输出和本机访问边界                                  |
| `application`           | `title`, `version`, `docs_enabled`, `redoc_enabled`, `openapi_enabled`, `docs_path`, `redoc_path`, `openapi_path`                                                                                                                                                                                                                                                             | FastAPI 标题、版本、文档路由与前端应用标识；不影响固定的 Hello 欢迎语 |
| `service`               | `startup_timeout_seconds`, `stop_timeout_seconds`                                                                                                                                                                                                                                                                                                                             | Shell 等待后台启动就绪和目标进程退出的期限，均为正秒数                |
| `database`              | `journal_mode`, `synchronous`, `pool_size`, `max_overflow`, `pool_timeout_seconds`                                                                                                                                                                                                                                                                                            | SQLite 日志与持久化模式、连接池容量和等待时间                         |
| `logging`               | `directory`, `filename`, `level`, `format`, `rotation`, `retention_days`, `compression`, `serialize`, `console`, `request_logging`                                                                                                                                                                                                                                            | Loguru 文件、等级、格式、轮转、保留、压缩、序列化与访问日志           |
| `telemetry`             | `tracing`, `metrics`, `logs`, `operation_spans`, `auto_configure`, `sampler`, `id_generator`, `sdk_disabled`, `internal_metrics_enabled`, `shutdown_on_exit`, `context`, `propagators`, `known_methods`                                                                                                                                                                       | 原生请求上下文、SDK 生命周期、传播协议与受控环境桥接                  |
| `telemetry.span_limits` | `max_attributes`, `max_events`, `max_links`, `max_span_attributes`, `max_event_attributes`, `max_link_attributes`, `max_attribute_length`, `max_span_attribute_length`                                                                                                                                                                                                        | 显式传入全部八项 SDK SpanLimits；随附值均为 0                         |
| `vite`                  | `host`, `port`, `proxy_target`, `strict_port`, `change_origin`                                                                                                                                                                                                                                                                                                                | 开发服务器地址、端口、严格端口策略和代理行为                          |
| `client`                | `request_timeout_seconds`, `query_stale_seconds`, `query_cache_seconds`, `query_retry_attempts`, `query_retry_delay_seconds`, `retry_min_status`, `retry_network_errors`, `refetch_on_window_focus`, `refetch_on_mount`, `refetch_on_reconnect`, `mutation_retry_attempts`, `theme_primary_color`, `theme_border_radius`, `theme_font_size`, `theme_font_family`              | 请求超时、查询缓存/重试/刷新、写重试约束、组件主题                    |
| `testing`               | `temporary_directory`, `host`, `termination_grace_seconds`, `command_timeout_seconds`, `keep_artifacts`, `browser`, `viewport_width`, `viewport_height`, `mobile_width`, `mobile_height`, `workers`, `retries`, `test_timeout_seconds`, `expect_timeout_seconds`, `action_timeout_seconds`, `navigation_timeout_seconds`, `trace`, `screenshot`, `fully_parallel`, `reporter` | 临时目录、进程预算、浏览器、视口、并行度、重试、超时和诊断产物        |

随附取值、单位和逐项说明见[主 TOML](../configs/app.toml)，字段类型、范围与跨字段约束由 [backend/app/config.py](../backend/app/config.py) 定义并执行校验，三者同步维护。TOML 中提供的数值是操作者选择的值，不是缺失时的默认值；注释不参与解析，也不产生额外配置项。

`ApplicationSettings` 提供只读派生属性 `docs_url`、`redoc_url`、`openapi_url`，将各自必填的启用开关和路径转换为有效路径或 `None`，应用工厂直接读取。它们不是新增 TOML 字段，不进入配置导出；关闭功能仍需提供原始 `*_path`，供前端保留这些路径并返回真实 404。OpenAPI 与交互文档开关的关联校验保持不变，不允许关闭 OpenAPI 时启用 Swagger 或 ReDoc。

`LoggingSettings.compression_format` 是供日志初始化读取的只读派生属性，将必填的 `logging.compression` 中的 `"none"` 转为 `None`，`"gz"` 和 `"zip"` 保持原值；它不是 TOML 字段，也不进入配置导出。配置文件与导出结果仍使用原始的 `compression` 字符串。

日志输出的固定策略也集中在 `LoggingSettings`：`backtrace = false`、`diagnose = false`、`enqueue = true`、`colorize = false`、`catch = true`。这些是使用 `ClassVar` 声明的代码级类属性，不是可由 TOML 设置的字段，不进入配置导出或 JSON Schema；在 `[logging]` 中添加同名键仍按未知字段拒绝。日志初始化统一读取这些属性，文件与控制台输出沿用相同策略。

- `logging.retention_days = 0` 显式表示保留所有轮转日志。
- 并发上限固定为不限，不传 --limit-concurrency；不读取任何同名环境覆盖。
- `testing.action_timeout_seconds = 0` 显式关闭单动作超时。
- `false`、`0` 和空的允许列表会按其真实含义使用，不通过 `or`、`??` 或模型默认值替换。
- 浮点时间必须有限，不接受 `inf` 或 `nan`。

所有相对路径均相对于项目根目录，支持绝对路径。`data_dir`、数据库文件名、备份目录和日志目录独立配置。修改数据目录时也需核对备份目录。

随附配置使用 `.data/app.sqlite3` 保存数据库，使用 `.data/backups/` 保存备份；`.data/` 整体被 Git 忽略。相对路径的解析规则不因目录以点开头而改变。

应用 lifespan 与 `db-upgrade` 共用数据库旁的文件锁，例如 `.data/app.sqlite3.lock`，路径属于固定安全机制，不额外增加配置项。锁在关闭连接后或进程退出时释放，文件可以保留；运行期间不要删除。切换数据库路径或执行迁移前先停止服务；文件锁只约束使用同一机制的本机进程。

应用加载和项目生成共用 `backend/app/utils/path_safety.py`，按路径用途分别检查：

- 数据、备份与日志是私有目录，不得与受保护源码、项目根的依赖/工具缓存目录、固定服务目录 `.run/` 或公开输出双向重叠。默认 `.data/`、`.data/backups/` 与 `logs/` 是允许的私有路径，私有目录之间不统一禁止包含关系。
- 公开输出额外避开根目录的 `data/`、`.data/`、`logs/`、`.run/`，以及 `.venv/`、`node_modules/`、`.pytest_cache/`、`.ruff_cache/`。`frontend/` 内只允许 `frontend/dist/` 子树作为输出位置。
- 源码保护覆盖 根 `entrypoints/`（服务 Shell 入口）、`backend/`（包含 Python 入口）、`frontend/`、`scripts/`、`configs/`、`docs/`、`e2e/`、`.git/`、`.agents/`、`.codex/`、`.aws/` 及项目入口文件；根 `.prettierrc.toml` 和 `.prettierignore` 同样受保护，不能作为输出或私有运行目录。完整列表由路径策略模块维护。目录检查解析符号链接并折叠大小写，比较包含关系的两个方向。
- 自动清空只允许实际的 `frontend/dist`，其子目录或指向外部的符号链接不能启用自动清空。其他合法输出位置需显式设置 `frontend_clean_output = false`。

数据库、数据库操作锁与应用日志必须指向不同路径；同名文件也拒绝。固定 .run 只保存 instance.json、console.log 和原子更新期间的 pending 文件，不创建服务锁。记录格式仍为 3，身份只使用 PID 和系统启动时间，另存配置来源、URL、日志及停止期限。文件为当前用户所有的 0600 普通文件，拒绝符号链接；状态存在不是存活证据，必须核对系统进程。正常退出可保留记录。并发启停和记录丢失由运维控制，不提供互斥或强防重复启动保证；数据库维护锁机制不变。
`testing.temporary_directory` 是创建独占子目录的父位置，允许 `/tmp` 这样的外部父目录，但不得直接使用项目根目录、源码、固定 `.run/` 或公开输出目录。E2E 强制使用本次临时目录中的构建、数据和日志，不复用日常产物。

迁移开发命令 db-revision 与 db-check 使用这个父目录，始终清理本次临时子目录，不保留迁移数据库。CLI 校验并绑定完整 TOML，工具用配置中的文件名在独占临时目录内确定 database_path，通过 Alembic 上下文传给引擎；不复制 Settings，不重新绑定或修改 config.settings。迁移不进入应用 lifespan，不创建配置中的日志、备份或前端产物，原数据库也不连接；实际临时目标仍通过路径安全检查。连接参数沿用所选 TOML，不增加配置字段或环境变量来源。db-upgrade 和 db-backup 仍操作 TOML 指定的应用数据库，步骤和迁移脚本能力边界见[数据库指南](database.md#迁移生成审查与验证)。

创建器保持标准库实现，只校验路径、源文件完整性和创建过程所需的关键字段；完整 Pydantic 字段、枚举和跨字段校验由生成项目的 `export-settings`、测试或首次启动执行。

随附 `.gitignore` 覆盖默认路径和常见产物；自定义任意文件名或目录后仍需检查 Git 忽略规则。生成器仅为新项目补入配置路径，不会修改原模板的 `.gitignore`。

## 前后端配置流

```text
service.sh 中的固定参数 ── Uvicorn CLI
configs/app.toml ── Python tomllib + Pydantic 完整校验
       ├── 应用工厂 / lifespan / 数据库 / Loguru
       └── 本地构建工具的受控 JSON 交换
                    ├── Vite / Playwright
                    └── 浏览器白名单：client + 应用标题/版本
```

Vite 和 Playwright 使用同一配置校验器，不各自猜测字段或填默认值。构建前需要先安装后端依赖。浏览器包不包含数据目录、日志目录、完整服务设置或访问允许列表。

后端参数修改后重启；前端运行参数和组件主题在构建时注入，修改后重新构建再刷新。Vite 开发模式重新启动开发服务器即可读取新值。

`client.theme_primary_color` 设置 Semi Design 主色及其交互状态，`client.theme_border_radius` 设置 Semi 的小圆角变量，供按钮、标签和行内提示等组件使用。`client.theme_font_size` 与 `client.theme_font_family` 用于 Hello 页的重新检查按钮与错误提示正文。页面品牌和布局由页面样式定义。

## 保留在代码中的固定契约

配置化的边界是可调运行参数。以下内容属于协议、完整性或安全规则，固定在代码中：

- API 业务路径、operation ID、HTTP 方法和响应/错误字段；界面状态文案和页面布局设计。
- 运维保证实例排他使用和管理命令串行；固定 `.run/` 与服务文件名、单 worker、严格端口、Uvicorn 原生信号处理与关闭、数据库维护锁、启动失败的非零退出码与不按端口杀进程；进程身份核对、运行文件命名、状态退出码与 0.1 秒轮询间隔。
- SQLite 外键、显式事务、禁止跨并发任务共享 AsyncSession、参数隐藏、最低安全版本、只读连接与独占备份创建。
- 日志追加、UTF-8、关闭局部变量诊断和回溯扩展、单 worker 队列后台写入、lifespan 退出时等待应用阶段日志，以及标准日志桥接规则；不额外承诺 Uvicorn 末尾日志排空。
- 前端私有信息隔离、禁止通过配置绕过服务与迁移互斥或把源代码/数据目录作为公开构建输出。
- 源码/测试目录、生成文件名、测试用例数据、页面测试健康检查、CLI 交换缓冲上限与秒/毫秒换算。
- 第三方库尚未在本项目启用的功能，不额外制造配置项。

原生 telemetry 的采集关闭约束及 SDK 参数边界见下节，属于代码校验的固定能力范围。保留 SDK 并创建上下文不等于开启采集。

SQLite 完整性基线及检查方式统一见[数据库指南](database.md#sqlite-版本要求)，没有通过应用配置绕过版本检查的开关。

错误响应的空详情列表、非请求日志的链路标识占位符和加载/错误文案属于协议或界面语义，不是配置缺失后的兜底参数。

## 遥测上下文与环境隔离

本项目只维护请求上下文，使用 FastAPI 原生 telemetry 和锁定的 OTel API/SDK 1.45.1。`telemetry.tracing = true`、`sdk_disabled = false` 保证 SDK 能创建有效上下文；采样器只接受 `always_off`，ID 生成器只接受 `random`，上下文实现只接受 `contextvars_context`，传播器只接受 `tracecontext`。其余六个布尔开关必须为 false：`metrics`、`logs`、`operation_spans`、`auto_configure`、`internal_metrics_enabled`、`shutdown_on_exit`。值违反范围时在配置校验阶段失败，不通过默认值修正。全部字段均必填。

`app` 包首先清除当前进程中继承的全部 `OTEL_*` / `FASTAPI_OTEL_*` 键，不记录其值。这样第三方模块在首次导入时不会消费外部 propagator、context、SDK 默认限制或导出配置。应用工厂在 SDK 导入和 provider 构建前再次清理，再用 TOML 值填充以下固定白名单；对 shell 和其他进程没有影响，请求期间不修改环境。

| SDK/FastAPI 环境入口                       | TOML 字段                            | 用途                                                                 |
| ------------------------------------------ | ------------------------------------ | -------------------------------------------------------------------- |
| `OTEL_SDK_DISABLED`                        | `telemetry.sdk_disabled`             | 防止 SDK 被外部值变成 NoOp                                           |
| `OTEL_PYTHON_SDK_INTERNAL_METRICS_ENABLED` | `telemetry.internal_metrics_enabled` | 禁用 SDK 自身指标                                                    |
| `OTEL_PYTHON_CONTEXT`                      | `telemetry.context`                  | 明确支持的 contextvars 上下文实现                                    |
| `OTEL_PROPAGATORS`                         | `telemetry.propagators`              | 明确 W3C tracecontext；同时用公开 API 安装该传播器，覆盖已有模块缓存 |
| `OTEL_INSTRUMENTATION_HTTP_KNOWN_METHODS`  | `telemetry.known_methods`            | FastAPI 原生 HTTP 方法归类，列表序列化为逗号分隔值                   |
| `FASTAPI_OTEL_AUTO_CONFIGURE`              | `telemetry.auto_configure`           | 禁止自动初始化导出组件；FastAPI 参数也显式设为同一配置值             |

采样器、随机 ID 生成器和八项 SpanLimits 通过构造参数传入；Resource 的 service.name、service.version 取 application.title、application.version，直接构造，不调用自动环境探测。真实 SDK provider 仅由 lifespan 内的 tracer_provider_scope() 创建并持有，退出时先清除模块引用再 shutdown；重复初始化报错，不影响原作用域。应用构建只注入不持有 SDK 资源的 TracerProviderAdapter，tracer 只保留插桩元数据，每次 span 操作取得当前 provider，避免 FastAPI 缓存已关闭的 SDK tracer。未初始化、已关闭或创建失败时不自动补建。适配层只使用 OpenTelemetry 公共接口，不修改 FastAPI 私有属性，也不设置全局 tracer/meter/logger provider；NoOp meter 和禁止采集/导出策略不变。OpenAPI 导出不创建真实 provider，无需 shutdown。

环境白名单只是第三方参数通道，不能作为第二个配置来源。未使用的 exporter、资源探测器和自动插桩入口保持不配置，外部同名前缀变量被丢弃。该入口管理整个单应用进程；如果宿主在导入 `app` 前已初始化第三方 OTel 实现，其先前副作用无法由应用撤销，运行入口应遵循本项目的 sh/CLI 顺序。

随附日志格式继续使用 `{extra[trace_id]}`，非请求日志使用 `-` 占位；正常响应和错误响应均返回当前服务端上下文的标准 `traceparent` 头，其中 trace ID 与错误体、500 日志一致。不返回 `X-Trace-ID`，也不原样回显上游 parent ID；不增加响应头名称配置开关。请求头缺失或无效时由 SDK 创建上下文，应用层没有 UUID 生成回退。trace ID 不再受 UUIDv7 格式约束，备份文件的 UUIDv7 命名不受影响。

额外私有路径校验使用独立标签，不能使用 `frontend_dir`、`data_dir`、`backup_directory` 或 `logging.directory` 覆盖内置路径；公开输出必须始终以原始 frontend_dir 参数进行保护校验。

`Settings.source_file` 是由 loader 或原始文档校验入口绑定的只读来源元信息，不是 TOML 字段，不进入配置导出或 Schema。直接构造或 `model_validate` 得到的 Settings 没有来源，服务入口访问该属性时明确报错，不默认使用其他配置文件。

## 引导入口与迁移

固定入口 `configs/app.toml` 和项目根目录定位是引导约定，不是运行字段的默认值。否则配置文件必须先告诉程序它自己的位置，会形成循环。`--config` 用于真正启动新实例时选择完整 TOML；需要读取配置时，文件不存在即失败，不遍历其他文件或环境变量。已有实例的 `start/run` 和全部 `status/stop` 调用不读取该文件。

旧 `configs/app.json` 已移除，没有格式兼容回退。自定义旧 JSON 需要按主 TOML 的完整字段清单迁移；旧的本地私有 JSON 仍被 Git 忽略，防止误提交，但不会被加载。

服务入口必须显式指定 run/start/status/stop/restart，无参数不隐式启动。start/run 检查到已有匹配实例时提示并返回 0，否则加载配置；status/stop 仅使用保存的实例状态，不加载 TOML。新实例默认选择项目根 configs/app.toml，使用 --config 另选。service 分组仍只有两个必填等待期限，旧字段和 logging.bootstrap_filename 按未知字段拒绝，不补值或合并。所有配置共用项目根 .run，但服务管理不加锁，也不保证并发调用只启动一个实例；运维负责串行管理。restart 先预校验目标 TOML，停止成功后启动，不冻结跨进程配置；默认配置路径不沿用旧实例设置。目标数据库仍须通过显式维护 CLI 准备，维护前核对目标配置，不用 --config 选择要停止的实例。操作语义见 [README 的服务控制](../README.md#服务控制)。

## 验证

- 逐一删除配置表或字段，验证所有项均不可省略。
- 验证错误类型、未知字段、非有限超时被拒绝，零值和 false 不被替换。
- 验证文件中的数据库池容量、日志模式、持久化模式、文档开关和应用标识实际生效。
- 回归五个显式服务子命令、前后台日志清理、重复启停、进程身份不匹配拒绝、首次并发启动、遗留状态、启动失败回收、停止超时不重启、运行期间迁移互斥及 Chromium 欢迎页；服务测试使用独立临时项目副本隔离固定 `.run/`，服务测试只修改临时 Shell 常量，并使用临时 TOML、日志和数据库。

页面测试遵守 `testing.screenshot`，不强制绕过截图配置。验证还需检查前端公开白名单，确认构建 JavaScript 不包含私有存储或日志路径。历次实际检查见 [实现与验证记录](history.md)。

数据库执行栈固定为 SQLAlchemy 2.0 AsyncEngine/AsyncSession + aiosqlite，没有同步驱动回退开关；该技术选型属于架构契约，不额外制造配置项。`database.synchronous` 调整的是 SQLite 持久化级别。

运行文件保护由 service.sh 的 check_files 执行，stat 检查所有者/0600，拒绝符号链接，jq 校验记录结构；status/stop 同样受保护。Shell 在 exec 前登记 PID/系统启动时间，Python 装配阶段不写状态。配置校验与应用装配分别读取 TOML，不承诺冻结快照。

项目根 `private/` 整棵目录只用于私有材料，公开 `frontend_dir` 不得与其双向重叠，包括大小写与符号链接别名；私有数据、备份、日志等仍可使用各自的 `private/` 子目录。此规则由应用与项目创建器共用的路径策略执行。
