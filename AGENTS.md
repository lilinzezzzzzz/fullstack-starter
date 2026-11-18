# 项目协作规则

## 范围与指令入口

- 本项目是本地、单用户、单机的 FastAPI + SQLite + React 脚手架。唯一示例是 Hello 页面与 API；任务未要求时，不增加业务表、CRUD 应用、认证、队列或部署基础设施。
- 本文件适用于整个项目。修改某个目录前，读取下表中对应的指令；子目录文件补充本目录特有约束，不重复通用协作规则。跨目录修改需同时核对各方契约。

| 修改范围                           | 专属指令                                                                       |
| ---------------------------------- | ------------------------------------------------------------------------------ |
| 后端 Python、CLI 与服务管理实现    | [backend/AGENTS.md](backend/AGENTS.md)                                         |
| 项目级服务 Shell 入口              | [backend/AGENTS.md](backend/AGENTS.md)，唯一入口为 `entrypoints/service.sh`    |
| Alembic 环境、迁移历史与开发工具   | [backend/migrations/AGENTS.md](backend/migrations/AGENTS.md)，同时遵循后端规则 |
| 页面、客户端、构建、接口类型与 E2E | [frontend/AGENTS.md](frontend/AGENTS.md)                                       |
| 项目创建器                         | [scripts/AGENTS.md](scripts/AGENTS.md)                                         |
| 技术文档                           | [docs/AGENTS.md](docs/AGENTS.md)                                               |

## 跨目录契约

- 当前架构以 [docs/design.md](docs/design.md) 为依据；[README.md](README.md) 提供常用命令与文档入口，创建及数据库操作细节分别维护在 [docs/project-creation.md](docs/project-creation.md) 与 [docs/database.md](docs/database.md)，配置边界维护在 [docs/configuration.md](docs/configuration.md)，有日期的实测证据维护在 [docs/history.md](docs/history.md)。发现实现与约定不符时，说明差异，不能仅凭当前行为改写设计要求。
- 默认由 FastAPI 托管构建后的前端，Vite 仅用于可选开发。不增加 Makefile、根目录前端工作区包或前后端统一进程管理器。
- Uvicorn 启动参数固定在 service.sh，不读取 .env 或环境变量覆盖。应用配置只读取显式 configs/app.toml，另选文件使用 --config；所有字段及分组必填，拒绝未知字段，不从环境变量、旧 JSON、模型默认值或回退表达式补值，保留 0、false 和空列表。相对路径从项目根解析。
- 配置变更同步 Python 校验器、随附 TOML、配置文档和相关测试；构建工具复用同一 Python loader。浏览器只接收 `client` 与应用标题、版本，前端配置变更需重新构建。工具的 PATH、缓存和浏览器安装位置不属于应用配置来源。
- API 成功体直接遵循响应 Schema；错误包含 `code`、`message`、`details`、`trace_id`。响应通过标准 `traceparent` 返回当前服务端上下文，不原样回显上游 span，不返回 `X-Trace-ID`。未知 API 和缺失资源返回真实 404，不落入 SPA HTML。
- 接口 Schema 或公开客户端配置类型变更后，更新 `frontend/src/types/api.generated.d.ts`；通过生成器维护，禁止手改。生成和检查命令见前端指令与 README。
- 数据库结构通过 Alembic 显式升级；导入应用和导出 OpenAPI 不连接数据库、不创建日志、不要求前端产物。启动检查交给 lifespan，不在启动时迁移或建表。
- lifespan 初始化后，应用、请求和 Uvicorn 日志统一使用 Loguru；进入 lifespan 前的 Uvicorn 启动消息保留原生控制台输出。原生 telemetry 只维护 trace 上下文，采样与采集边界见后端指令。

## 运行与数据安全

- 服务唯一入口为 `sh entrypoints/service.sh run|start|status|stop|restart`，不提供独立启动脚本或隐式启动命令。前后台共用脚本内的 Uvicorn CLI 启动逻辑，导入 `entrypoints.api:app`。服务管理不加锁，由运维保证命令串行和实例排他使用；固定 .run 只保存 instance.json、console.log 及原子更新期间的 pending 文件。数据与日志仍取 TOML，数据库维护锁不变。根 entrypoints 只放 service.sh，Python 实现仍在 backend/entrypoints。
- 服务和显式升级共用数据库专属文件锁，运行期间不删除锁文件。日常数据库升级、恢复和切换前先停服，并遵守用户授权边界；文件锁不代表其他数据库使用者已经停止。
- 服务验证使用独立临时项目，只重写临时 Shell 的 host 和 port 常量，配套独占 TOML、SQLite、日志、构建及自有进程，不操作日常 .run、.data、日志、备份、服务或前端产物，也不读取或改动私有 .env。只清理本次资源，保留取消传播和连接关闭。
- 保持数据库、WAL/SHM、服务实例凭据与状态、锁、备份、日志、私有配置、依赖、缓存和构建输出不进入 Git；自定义运行路径时同步检查 `.gitignore` 与源码路径保护。

## 工具与验证

- 解释器和依赖版本以 `backend/.python-version`、`.node-version`、`frontend/package.json` 及两份锁文件为准；使用 uv / pnpm，不因文档整理或局部修改顺带升级依赖。
- 检查命令均从项目根运行，默认执行最小充分验证，按实际 diff、受影响行为和具体未验证风险选择；各目录规则提供领域检查，README“接口类型与验证”列出可用命令，不表示每轮都要全部执行。
- 局部修改先运行相关测试，不将完整后端回归、完整构建或全部 Chromium E2E 作为固定步骤。只有影响范围较广、共享契约变化、定向测试暴露关联问题，或存在具体未验证风险时，才扩大检查范围。
- Chromium E2E 仅在浏览器行为、前端托管、构建注入、接口调用链、E2E 运行器变化，或阶段性验收确有需要时执行。服务管理脚本通常先做隔离启停、身份、信号和超时专项；启动链路调整完成后可按需要做一次整体浏览器验收，不逐次重复四项页面测试。
- 同一阶段已通过的检查，在相关代码未变化时不重复运行；后续只修改文档，不重跑应用或浏览器测试。失败后先重跑失败用例及直接关联测试，通过后再按实际影响决定是否扩大。
- 执行较重的全量检查前，简要说明要验证的具体风险，不以“更保险”为由无依据地重复检查；不新增每次测试都需用户确认的流程。用户明确要求完整回归或 E2E 时，按要求执行。
- 纯指令或文档修改只检查格式、路径、链接、标题、代码块及规则冲突，并执行 `git diff --check`；不为此运行后端回归、构建或浏览器 E2E，也不把文档检查报告成应用行为验证。
- 完成时说明实际修改、已运行检查和未验证范围；保留无关工作，不自动暂存、提交、推送或操作日常服务。

## 服务管理共同契约

- service.sh 直接实现 run、start、status、stop、restart 五个命令，负责实例记录、PID/启动时间、健康、信号和等待，不委托 Python 控制器。api.py 只保留 create_app 导入和 app = create_app()，日志在 lifespan 初始化；cli.py 的 export-service-settings 导出配置。config.py 用 lazy_proxy 导出固定 settings 属性读取代理，get_settings() 缓存真实实例，bind_settings() 只改变内部绑定，不替换代理。后端统一读取 config.settings，不保存 app.state.settings 或转传 Settings；真实类型和序列化操作使用 getter 或 loader 的真实对象。CLI 严格加载 --config 后绑定，再执行操作；运行期间不重绑，不交错运行不同配置的应用。临时迁移只传 database_path；测试通过绑定接口隔离缓存并在资源关闭后恢复，包括未加载状态。load_settings(path) 独立加载，不读写缓存。删除 service.py 和 service_control.py，不保留服务锁、TCP 通道、凭据或快照。
- Shell 固定 Uvicorn 的 host=127.0.0.1、port=18001、关闭期限10秒、Keep-Alive5秒、backlog2048、单worker，并发不限（省略 --limit-concurrency）。host 和 port 在脚本内各有单一常量供启动和记录复用，其他参数直接写在 CLI 中；不读取 .env，不提供 --env-file，server_environment.py 已删除。Python 仅导出 TOML 来源、日志和两个等待期限。Shell 使用实例记录中的停止预算，该预算独立于 Uvicorn 的优雅关闭等待。创建器的 --port 修改生成副本的端口常量，隔离测试只修改临时副本的 host 和 port。
- 五个命令均不使用服务锁，不传递锁描述符或 --locked 内部参数。后台子进程调用同一脚本的 run 路径；已有匹配实例时返回 0，不读新配置。检查已有实例仅方便串行使用，不提供并发启动保护；运维负责避免并发启停和管理记录丢失。status/stop 不读取配置文件。
- restart 先预校验所选 TOML，失败保留旧实例；停止成功后启动新实例。默认选择 configs/app.toml，不保证跨进程配置冻结或并发互斥，运维负责串行调用和配置变更。
- 不创建服务锁，不清理日常旧文件。Shell 在 exec Uvicorn 前记录自身 PID/系统启动时间，exec 后 PID 不变；格式仍为 3，另存配置、URL、日志和停止期限。jq 校验记录，stat 检查 0600/所有者，并拒绝符号链接；pending 原子替换。正常退出可留下记录，stop 在原目标退出后清理匹配记录，不自动接管旧格式。
- 存活和停止身份只核对 PID 与系统启动时间，启动时间读取固定 C/UTC 下的系统记录，僵尸进程视为已退出。停止核对后发 SIGINT，并持续等待原目标进程退出；记录丢失不能使已开始的停止等待提前成功，超时不强杀，失败不继续重启。健康仍核对监听归属和 HTTP/JSON。没有生命周期运行锁后，记录丢失会削弱防重复启动保证；检查与发信号之间仍有 PID 复用竞态。数据库维护锁只约束同一数据库，不替代实例发现。
- 服务停止由 Uvicorn 原生处理，不接管或转换其退出信号，不注册自定义进程退出钩子，也不额外承诺 Uvicorn 末尾日志排空或重复信号屏蔽。lifespan 的应用清理保持不变：关闭数据库连接、释放数据库维护锁、关闭 provider 并等待应用阶段日志。数据库维护互斥机制不变。
- 管理成功 0，status 已停止 3，参数错误 2，其他错误 1，管理命令中断为 130/143；前台 run 透传 Uvicorn 原生结果。后台由 Shell 用 nohup 启动并等待健康，忽略 SIGHUP，不额外创建独立会话。等待使用自有 sleep 计时子进程，退出时清理；失败只回收本次新建服务，不强杀，不继续重启，不停止既有查询目标。管理命令依赖 jq、ps、stat、lsof、curl、nohup 等工具，status/stop 不调用 Python 或 uv。
