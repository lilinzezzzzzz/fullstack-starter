# 项目协作规则

## 范围与指令入口

- 本项目是本地、单用户、单机的 FastAPI + SQLite + React 脚手架。唯一示例是 Hello 页面与 API；任务未要求时，不增加业务表、CRUD 应用、认证、队列或部署基础设施。
- 本文件适用于整个项目。修改某个目录前，读取下表中对应的指令；子目录文件补充本目录特有约束，不重复通用协作规则。跨目录修改需同时核对各方契约。

| 修改范围                           | 专属指令                                                                       |
| ---------------------------------- | ------------------------------------------------------------------------------ |
| 后端、CLI 与服务启动实现           | [backend/AGENTS.md](backend/AGENTS.md)                                         |
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

- 通过 `sh entrypoints/service.sh` 前台运行单 API worker，Ctrl+C 停止；Uvicorn 负责信号与优雅关闭。不恢复后台 PID 管理、就绪轮询或额外根启动脚本，不因端口占用而终止其他进程。修改该入口时同时读取后端指令。
- 服务和显式升级共用数据库专属文件锁，运行期间不删除锁文件。日常数据库升级、恢复和切换前先停服，并遵守用户授权边界；文件锁不代表其他数据库使用者已经停止。
- 验证使用独占临时 TOML、SQLite、日志、构建目录和自有服务进程，不操作日常 `.data/`、日志、备份、服务或前端产物。只清理由本次验证创建的资源，保留取消传播和连接关闭。
- 保持数据库、WAL/SHM、锁、备份、日志、私有配置、依赖、缓存和构建输出不进入 Git；自定义运行路径时同步检查 `.gitignore` 与源码路径保护。

## 工具与验证

- 解释器和依赖版本以 `backend/.python-version`、`.node-version`、`frontend/package.json` 及两份锁文件为准；使用 uv / pnpm，不因文档整理或局部修改顺带升级依赖。
- 检查命令均从项目根目录运行。按变更范围先做定向验证；后端、前端、迁移与项目生成的具体检查见各目录指令，完整命令见 README 的“接口类型与验证”。
- 纯指令或文档修改检查路径、链接、标题、代码块与规则冲突，并执行 `git diff --check`；不把文档检查报告成应用行为验证。
- 完成时说明实际修改、已运行检查和未验证范围；保留无关工作，不自动暂存、提交、推送或操作日常服务。
