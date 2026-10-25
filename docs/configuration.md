# 配置审查与使用约定

## 结论与格式选择

本项目的应用配置入口为 [configs/app.toml](../configs/app.toml)。当前有 **86 个叶子配置项**，所有字段和分组都必须显式提供。缺项、未知项、错误类型或无效数值直接报错，不由代码、环境变量、`.env` 或旧 JSON 文件补齐。

JSON 是可靠的机器交换格式，适合 API、生成数据和工具元信息。这里的配置主要由人维护，字段增加后需要分组和注释，因此选择 TOML。它不是对所有项目都最优，而是更适合当前 Python 主导、前后端同仓库的小型脚手架。[TOML 规范](https://toml.io/en/)

Python 3.14 使用原生 `tomllib` 解析 TOML 1.0，再由 Pydantic 统一校验；标准库不提供写入能力，测试使用开发依赖 `tomli-w`。Node 端测试使用 `smol-toml` 写入临时 TOML，实际应用值仍通过 Python 校验后取得。[Python tomllib 文档](https://docs.python.org/3.14/library/tomllib.html)

`package.json`、`tsconfig.json`、API JSON 和页面测试运行元信息仍遵循各工具或协议的原生格式，它们不是旧的应用 JSON 配置入口。

## 已收拢的运行参数

| 分组 | 必填字段 | 使用位置 |
| --- | --- | --- |
| 根配置 | `data_dir`, `database_filename`, `backup_directory`, `frontend_dir`, `serve_frontend`, `frontend_clean_output`, `sqlite_timeout_seconds`, `allowed_hosts`, `allowed_origins` | 数据库、备份、前端输出和本机访问边界 |
| `application` | `title`, `version`, `docs_enabled`, `redoc_enabled`, `openapi_enabled`, `docs_path`, `redoc_path`, `openapi_path` | FastAPI 标题、版本、文档路由；Hello 与前端应用标识 |
| `server` | `host`, `port`, `workers`, `graceful_shutdown_seconds`, `keep_alive_seconds`, `backlog`, `concurrency_limit` | 单 worker 启动、优雅关闭、Keep-Alive、backlog、并发上限 |
| `database` | `journal_mode`, `synchronous`, `pool_size`, `max_overflow`, `pool_timeout_seconds` | SQLite 日志与持久化模式、连接池容量和等待时间 |
| `logging` | `directory`, `filename`, `bootstrap_filename`, `level`, `format`, `rotation`, `retention_days`, `compression`, `serialize`, `console`, `request_logging` | Loguru 文件、等级、格式、轮转、保留、压缩、序列化与访问日志 |
| `service` | `pid_file`, `startup_timeout_seconds`, `shutdown_timeout_seconds`, `inspection_timeout_seconds`, `readiness_poll_seconds`, `shutdown_poll_seconds` | PID 文件、启动/停止等待、进程检查超时与轮询间隔 |
| `vite` | `host`, `port`, `proxy_target`, `strict_port`, `change_origin` | 开发服务器地址、端口、严格端口策略和代理行为 |
| `client` | `request_timeout_seconds`, `query_stale_seconds`, `query_cache_seconds`, `query_retry_attempts`, `query_retry_delay_seconds`, `retry_min_status`, `retry_network_errors`, `refetch_on_window_focus`, `refetch_on_mount`, `refetch_on_reconnect`, `mutation_retry_attempts`, `theme_primary_color`, `theme_border_radius`, `theme_font_size`, `theme_font_family` | 请求超时、查询缓存/重试/刷新、写重试约束、组件主题 |
| `testing` | `temporary_directory`, `host`, `termination_grace_seconds`, `command_timeout_seconds`, `keep_artifacts`, `browser`, `viewport_width`, `viewport_height`, `mobile_width`, `mobile_height`, `workers`, `retries`, `test_timeout_seconds`, `expect_timeout_seconds`, `action_timeout_seconds`, `navigation_timeout_seconds`, `trace`, `screenshot`, `fully_parallel`, `reporter` | 临时目录、进程预算、浏览器、视口、并行度、重试、超时和诊断产物 |

具体取值、单位与注释以主 TOML 文件为准。提供在文件里的数值是操作者选择的值，不是缺失时的默认值。

- `logging.retention_days = 0` 显式表示保留所有轮转日志。
- `server.concurrency_limit = 0` 显式表示不设置并发上限。
- `testing.action_timeout_seconds = 0` 显式关闭单动作超时。
- `false`、`0` 和空的允许列表会按其真实含义使用，不通过 `or`、`??` 或模型默认值替换。
- 浮点时间必须有限，不接受 `inf` 或 `nan`。

所有相对路径均相对于项目根目录，支持绝对路径。`data_dir`、数据库文件名、备份目录、日志目录和 PID 路径独立配置。修改数据目录时也需核对备份目录。

## 前后端配置流

```text
configs/app.toml
       │ Python tomllib + Pydantic 完整校验
       ├── 后端服务 / 数据库 / Loguru / PID 控制
       └── 本地构建工具的受控 JSON 交换
                    ├── Vite 开发 / 构建参数
                    └── 浏览器白名单：client + 应用标题/版本
```

Vite 和 Playwright 使用同一配置校验器，不各自猜测字段或填默认值。构建前需要先安装后端依赖。浏览器包不包含数据目录、日志目录、PID 文件、完整服务设置或访问允许列表。

后端参数修改后重启；前端运行参数和组件主题在构建时注入，修改后重新构建再刷新。Vite 开发模式重新启动开发服务器即可读取新值。

## 保留在代码中的固定契约

配置化的边界是可调运行参数。以下内容属于协议、完整性或安全规则，固定在代码中：

- API 业务路径、operation ID、HTTP 方法和响应/错误字段；界面状态文案和页面布局设计。
- 单 worker、严格端口、本地进程身份核对、SIGTERM、PID 文件格式、退出码与不按端口杀进程。
- SQLite 外键、显式事务、禁止跨并发任务共享 AsyncSession、参数隐藏、最低安全版本、只读连接与独占备份创建。
- 日志追加、UTF-8、关闭局部变量诊断和回溯扩展、单 worker 同步文件写入，以及标准日志桥接规则。
- 前端私有信息隔离、禁止通过配置绕过 PID 安全规则或把源代码/数据目录作为公开构建输出。
- 源码/测试目录、生成文件名、测试用例数据、进程就绪协议、CLI 交换缓冲上限与秒/毫秒换算。
- 第三方库尚未在本项目启用的功能，不额外制造配置项。

错误响应的空详情列表、非请求日志的请求标识占位符和加载/错误文案属于协议或界面语义，不是配置缺失后的兜底参数。

## 引导入口与迁移

固定入口 `configs/app.toml` 和项目根目录定位是引导约定，不是运行字段的默认值。否则配置文件必须先告诉程序它自己的位置，会形成循环。`--config` 只用于显式选择另一个完整 TOML 文件；文件不存在就失败，不遍历其他文件或环境变量。

旧 `configs/app.json` 已移除，没有格式兼容回退。自定义旧 JSON 需要按主 TOML 的完整字段清单迁移；旧的本地私有 JSON 仍被 Git 忽略，防止误提交，但不会被加载。

当前项目仅验证单 worker。修改 PID 路径前先停止服务，并始终使用启动时相同的配置文件路径执行停止操作。

## 验证

- 逐一删除配置表或字段，验证所有项均不可省略。
- 验证错误类型、未知字段、非有限超时被拒绝，零值和 false 不被替换。
- 验证文件中的数据库池容量、日志模式、持久化模式、文档开关和应用标识实际生效。
- 回归 sh/PID 生命周期及 Chromium 欢迎页；测试全部使用临时 TOML、日志、PID 和数据库。

页面测试遵守 `testing.screenshot`，不强制绕过截图配置。验证还需检查前端公开白名单，确认构建 JavaScript 不包含私有存储或 PID 路径。历次实际检查见 [实现与验证记录](history.md)。

数据库执行栈固定为 SQLAlchemy 2.0 AsyncEngine/AsyncSession + aiosqlite，没有同步驱动回退开关；该技术选型属于架构契约，不额外制造配置项。`database.synchronous` 调整的是 SQLite 持久化级别。
