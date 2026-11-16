# 项目协作规则

## 范围与指令入口

- 本项目是本地、单用户、单机的 FastAPI + SQLite + React 脚手架。唯一示例是 Hello 页面与 API；任务未要求时，不增加业务表、CRUD 应用、认证、队列或部署基础设施。
- 本文件适用于整个项目。修改某个目录前，读取下表中对应的指令；子目录文件补充本目录特有约束，不重复通用协作规则。跨目录修改需同时核对各方契约。

| 修改范围                           | 专属指令                                                                       |
| ---------------------------------- | ------------------------------------------------------------------------------ |
| 后端 Python、CLI 与服务管理实现    | [backend/AGENTS.md](backend/AGENTS.md)                                         |
| 项目级服务 Shell 入口              | [backend/AGENTS.md](backend/AGENTS.md)，入口为 `entrypoints/service.sh`        |
| Alembic 环境、迁移历史与开发工具   | [backend/migrations/AGENTS.md](backend/migrations/AGENTS.md)，同时遵循后端规则 |
| 页面、客户端、构建、接口类型与 E2E | [frontend/AGENTS.md](frontend/AGENTS.md)                                       |
| 项目创建器                         | [scripts/AGENTS.md](scripts/AGENTS.md)                                         |
| 技术文档                           | [docs/AGENTS.md](docs/AGENTS.md)                                               |

## 跨目录契约

- 当前架构以 [docs/design.md](docs/design.md) 为依据；[README.md](README.md) 提供常用命令与文档入口，创建及数据库操作细节分别维护在 [docs/project-creation.md](docs/project-creation.md) 与 [docs/database.md](docs/database.md)，配置边界维护在 [docs/configuration.md](docs/configuration.md)，有日期的实测证据维护在 [docs/history.md](docs/history.md)。发现实现与约定不符时，说明差异，不能仅凭当前行为改写设计要求。
- 默认由 FastAPI 托管构建后的前端，Vite 仅用于可选开发。不增加 Makefile、根目录前端工作区包或前后端统一进程管理器。
- 应用配置只读取显式 TOML；固定引导入口为 `configs/app.toml`，另选文件使用 `--config`。所有字段及分组必填，拒绝未知字段，不从环境变量、`.env`、旧 JSON、模型默认值或回退表达式补值；保留 `0`、`false`、空列表的真实含义。相对配置路径从项目根目录解析。
- 配置变更同步 Python 校验器、随附 TOML、配置文档和相关测试；构建工具复用同一 Python loader。浏览器只接收 `client` 与应用标题、版本，前端配置变更需重新构建。工具的 PATH、缓存和浏览器安装位置不属于应用配置来源。
- API 成功体直接遵循响应 Schema；错误包含 `code`、`message`、`details`、`trace_id`。响应通过标准 `traceparent` 返回当前服务端上下文，不原样回显上游 span，不返回 `X-Trace-ID`。未知 API 和缺失资源返回真实 404，不落入 SPA HTML。
- 接口 Schema 或公开客户端配置类型变更后，更新 `frontend/src/types/api.generated.d.ts`；通过生成器维护，禁止手改。生成和检查命令见前端指令与 README。
- 数据库结构通过 Alembic 显式升级；导入应用和导出 OpenAPI 不连接数据库、不创建日志、不要求前端产物。启动检查交给 lifespan，不在启动时迁移或建表。
- 应用、请求和 Uvicorn 日志统一使用 Loguru；原生 telemetry 只维护 trace 上下文，采样与采集边界见后端指令。

## 运行与数据安全

- 服务入口为 `sh entrypoints/service.sh run|start|status|stop|restart`，必须显式指定子命令；仅真正启动新实例时读取 `configs/app.toml`，另选文件使用 `--config`。`run` 前台运行单 API worker，Ctrl+C 停止；`start` 后台启动并等待健康检查，`stop/restart` 通过实例认证控制通道触发 SIGINT 并等待资源清理。只管理本项目实例，不按端口或孤立 PID 发信号，停止超时不强杀且不继续重启。每个项目只允许一个服务实例，所有配置共用根目录 `.run/`，不能通过更换数据库、端口或 `--config` 并行启动。实例记录、运行锁、控制锁和控制台输出分别为 `.run/instance.json`、`run.lock`、`control.lock` 和 `console.log`；数据库及其操作锁保留在 `.data/`，应用日志保留在 `logs/`（数据与应用日志路径仍取显式 TOML）。根目录 `entrypoints/` 只放 Shell 入口，不是 Python 包；Python 实现保留在 `backend/entrypoints/`，不保留旧 Shell 路径。修改入口时同时读取后端指令。
- 服务和显式升级共用数据库专属文件锁，运行期间不删除锁文件。日常数据库升级、恢复和切换前先停服，并遵守用户授权边界；文件锁不代表其他数据库使用者已经停止。
- 服务验证使用独立临时项目副本及其 `.run/`，并配套独占临时 TOML、SQLite、日志、构建目录和自有服务进程，不操作日常 `.run/`、`.data/`、日志、备份、服务或前端产物。只清理由本次验证创建的资源，保留取消传播和连接关闭。
- 保持数据库、WAL/SHM、服务实例凭据与状态、锁、备份、日志、私有配置、依赖、缓存和构建输出不进入 Git；自定义运行路径时同步检查 `.gitignore` 与源码路径保护。

## 工具与验证

- 解释器和依赖版本以 `backend/.python-version`、`.node-version`、`frontend/package.json` 及两份锁文件为准；使用 uv / pnpm，不因文档整理或局部修改顺带升级依赖。
- 检查命令均从项目根目录运行。按变更范围先做定向验证；后端、前端、迁移与项目生成的具体检查见各目录指令，完整命令见 README 的“接口类型与验证”。
- 纯指令或文档修改检查路径、链接、标题、代码块与规则冲突，并执行 `git diff --check`；不把文档检查报告成应用行为验证。
- 完成时说明实际修改、已运行检查和未验证范围；保留无关工作，不自动暂存、提交、推送或操作日常服务。

## 服务管理共同契约

- 五个子命令显式提供；`start/run` 在操作锁内先认证已有实例，有实例时提示并返回 0，不读取本次配置，无实例才加载并分别后台/前台启动。运行锁已占用但身份尚未登记时，`start/run` 只提示登记中并返回 0，不再启动；`status` 为 starting/1，`stop` 因无法认证目标返回 1，不发信号。这些结果不表示健康检查已经通过。
- `status/stop` 只用 `.run/instance.json` 的实际地址、身份和停止期限，忽略 `--config`，不读取 TOML。`restart` 在操作锁内读取、校验并冻结目标文档，停止旧实例后按同一快照启动；允许切换路径，省略参数固定使用 `configs/app.toml`。
- 后台子进程只接收匿名描述符中的原始 TOML 快照，配置字段由各自 Settings 校验，不将任何项目的专用字段写入通用控制层；原始 TOML 快照不写入具名文件；控制通道随机令牌仅写入 0600 的 `.run/instance.json` 及原子更新期间同权限的 `instance.json.pending`，不进入配置快照、日志、命令行或 Git。
- 使用认证回环控制通道，由目标进程自行发送 SIGINT；运行锁必须覆盖应用资源关闭、末尾日志排空、控制线程和实例记录清理。退出末尾忽略重复 SIGINT/SIGTERM，之后恢复原处理器。
- 所有 Ctrl+C 中断返回 130，包括运行中的前台 run；成功返回 0，status 已停止为 3，参数错误为 2，其余执行错误为 1。停止失败不继续重启，超时不强杀。
- 运行文件检查不依赖配置，拒绝 `.run` 和文件符号链接，凭据与运行文件权限为 0600；未知活跃协议拒绝控制，升级协议前使用原版本停服，不自动接管旧实例。

- 五个命令处理期间的 SIGTERM 均以 143 结束；前台 run 先优雅停服，后台启动等待中断时只回收该命令新建的子进程。只读查询中断不停止既有实例，停止等待中断不强杀目标、重启不继续启动。启动回收与退出末尾忽略重复 SIGINT/SIGTERM，结束后恢复调用前的处理器；服务控制命令和后端测试辅助器超时不强杀。E2E 运行器可最终强制回收自己创建的隔离临时进程，但超时必须失败并保留诊断，不得清理日常服务。
