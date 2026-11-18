# fullstack-starter

面向本地、单用户、单机应用的 FastAPI + SQLite + React 脚手架。默认由单 worker FastAPI 提供页面和 API；V1 只有 Hello 欢迎页、Hello API 与数据库健康检查，不创建业务表。

| 需要做什么           | 入口                                              |
| -------------------- | ------------------------------------------------- |
| 安装并运行           | [首次运行](#首次运行)                             |
| 创建独立的新项目     | [项目创建指南](docs/project-creation.md)          |
| 对齐正在开发的项目   | [已有项目架构对齐指南](docs/project-alignment.md) |
| 了解目录、分层与契约 | [代码入口](#代码入口)、[当前设计](docs/design.md) |
| 修改配置             | [配置约定](docs/configuration.md)                 |
| 备份、恢复或编写迁移 | [数据库维护与迁移](docs/database.md)              |
| 查看历史实测结果     | [实现与验证记录](docs/history.md)                 |

## 技术栈

- 后端：Python、uv、FastAPI、Pydantic v2、SQLAlchemy 2.0 async、aiosqlite、SQLite、Alembic、Loguru。
- 前端：Node.js、pnpm、React、TypeScript、Vite、React Router、TanStack Query、[Semi Design](https://github.com/DouyinFE/semi-design)、CSS Modules。
- 检查：Ruff、pytest、ESLint、Prettier、TypeScript、Playwright Chromium。

Python 与 Node.js 版本分别见 `backend/.python-version`、`.node-version`，pnpm 版本见 `frontend/package.json`；依赖由各自锁文件固定。已有 mise 和 Corepack 时，可用 `mise exec node@24.22.0 -- corepack pnpm@9.12.2 --dir frontend ...` 显式选择随附版本；调整工具版本后同步核对上述声明。

Python 实际链接的 SQLite 必须为 **3.51.3+**，这是本脚手架的完整性基线；检查与升级说明见[数据库指南](docs/database.md#sqlite-版本要求)。

运行入口依赖 POSIX sh，数据库文件锁使用 `fcntl`；当前没有原生 Windows 运行入口，实测平台与范围见[历史记录](docs/history.md)。

## 代码入口

| 职责               | 位置与边界                                                                                                                                                                                    |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 服务与维护入口     | [entrypoints/service.sh](entrypoints/service.sh) 提供五个管理命令；[backend/entrypoints/](backend/entrypoints/) 仅保留 ASGI app 入口及配置/OpenAPI、数据库维护 CLI                            |
| 应用装配           | [backend/app/application.py](backend/app/application.py)：无参数 `create_app()` 直接读取导入的 `settings` 装配应用，同文件 lifespan 初始化日志并管理运行资源；`entrypoints/api.py` 只暴露 app |
| 基础设施与底层工具 | [infra/](backend/app/infra/) 提供数据库、日志、静态托管与通用 HTTP 适配；[utils/](backend/app/utils/) 提供仅依赖标准库的路径策略、数据库锁和属性读取代理                                      |
| HTTP 与业务        | [routers/](backend/app/routers/)、[services/](backend/app/services/)、[schemas/](backend/app/schemas/) 分别承担请求适配、业务规则与接口结构；持久化结构放在 [models/](backend/app/models/)    |
| 浏览器与工程工具   | [frontend/src/](frontend/src/) 组织页面、请求和查询；[scripts/](scripts/) 提供独立项目创建器                                                                                                  |

依赖方向、资源关闭顺序和固定契约以[当前设计](docs/design.md)及各目录 `AGENTS.md` 为准。

## 已有项目架构对齐

先盘点现状、建立验证基线与职责映射，再试迁一条业务链路并逐批推进。保留原项目的业务、数据和对外契约，分别评估数据库、配置来源和部署方式等技术选择。

[架构对齐指南](docs/project-alignment.md)给出差异表、迁移顺序和验收要求；具体执行计划与进度保存在原项目中。

## 基于脚手架创建新项目

macOS/Linux 上准备 uv 和 rsync，在模板根目录执行：

```bash
sh scripts/create-project.sh \
  --name my-app \
  --target-dir /absolute/path/to/my-app \
  --port 18002 \
  --vite-port 5174
```

目标必须是模板之外尚不存在的目录；创建器不安装依赖、建库或启动服务。参数、复制边界与后续步骤见[项目创建指南](docs/project-creation.md)。

## 配置文件

Uvicorn 参数固定在 [service.sh](entrypoints/service.sh)：127.0.0.1:18001、关闭期限10秒、Keep-Alive5秒、backlog2048、单worker，并发不限。不读取 .env，也没有 --env-file 参数。应用配置仍只读取 [configs/app.toml](configs/app.toml)，所有字段必填，拒绝未知项及隐式补值，相对路径从项目根解析。

字段用途、单位、可选值和零值含义见 TOML 注释，定义与校验在 [backend/app/config.py](backend/app/config.py)。固定日志类属性和派生属性不属于 TOML 字段，不能通过添加同名键修改。

后端、Vite 与测试工具共用 Python 校验器。浏览器只接收 `client` 和应用标题/版本，前端配置变更需重新构建。配置来源、路径保护与 telemetry 环境隔离详见[配置约定](docs/configuration.md)。

普通运行时模块直接 from app.config import settings，在函数中读取配置；固定代理提前导入也不读取 TOML，telemetry 轻量入口仍在函数内延迟导入。CLI 和测试通过加载、getter 和绑定接口选择真实实例，不替换代理；运行期间配置不变。访问约定与导入边界见[配置说明](docs/configuration.md#python-配置访问)。

数据库引擎、备份和迁移工具直接使用导入的 settings，不再传递 Settings。临时迁移只显式传入独占数据库路径，连接参数仍取进程配置，不切换全局配置；路径缺失或无效时拒绝执行。具体边界见上述配置约定。

## 首次运行

选择上述工具版本后，从项目根目录执行。以下建库步骤适用于新空库；已有数据库先按[数据库指南](docs/database.md)检查版本与备份要求。

```bash
uv sync --directory backend --frozen
pnpm --dir frontend install --frozen-lockfile
uv run --directory backend python -m entrypoints.cli db-check
uv run --directory backend python -m entrypoints.cli db-upgrade
pnpm --dir frontend build
sh entrypoints/service.sh run
```

随附配置访问 [http://127.0.0.1:18001/](http://127.0.0.1:18001/)。启动时检查数据库版本与前端产物，不自动迁移、安装依赖或构建。

| 路径                               | 用途                                  |
| ---------------------------------- | ------------------------------------- |
| `/`、`/welcome`                    | Hello 欢迎页                          |
| `/api/v1/hello`                    | Hello API                             |
| `/api/health`                      | 服务和 SQLite 健康检查                |
| `/docs`、`/redoc`、`/openapi.json` | API 文档和 Schema，开关及路径取自配置 |

## 服务控制

唯一服务入口为 [entrypoints/service.sh](entrypoints/service.sh)，只提供 run、start、status、stop、restart 五个命令。前后台共用脚本内的启动逻辑，准备环境后直接 `exec python -m uvicorn entrypoints.api:app`；[api.py](backend/entrypoints/api.py) 只暴露 ASGI app。前台启动进程即 Uvicorn 进程，不保留父 Shell 或信号转发。

五个命令直接由 Shell 实现，使用 jq 读写记录、ps 核对 PID/启动时间、stat 检查权限、lsof/curl 检查监听与健康；需要 jq、ps、stat、lsof、curl、nohup 等本机工具。status/stop 不启动 Python 或 uv；Python 只在启动时校验配置并装配应用。服务管理不加锁，由运维保证串行和排他使用，支持项目外目录及含空格路径，不安装依赖、迁移数据库或构建前端。

| 命令      | 行为                                                               |
| --------- | ------------------------------------------------------------------ |
| `run`     | 无匹配实例时直接 exec Uvicorn，前台运行并优雅关闭                  |
| `start`   | 无实例才校验配置，用 nohup 后台启动，监听归属与健康 API 通过后成功 |
| `status`  | 核对 PID、系统启动时间和健康 API，不读取配置                       |
| `stop`    | 核对身份后发 SIGINT，交给 Uvicorn 原生处理并等待进程退出，不读配置 |
| `restart` | 先预校验配置，停止成功后后台启动，不冻结配置或提供并发互斥         |

```bash
sh entrypoints/service.sh start
sh entrypoints/service.sh status
sh entrypoints/service.sh restart --config configs/app.local.toml
sh entrypoints/service.sh stop
sh entrypoints/service.sh run
```

命令仅用 --config 另选应用 TOML；已有匹配实例时 start/run 返回0。前台 run 不套用后台启动预算。创建器仍接受 --port，在生成副本中重写 Shell 端口常量；隔离测试同样只修改临时脚本，不占用日常端口。

默认配置为 configs/app.toml，相对参数从项目根解析。已有实例的 start/run 和全部 status/stop 不读取指定配置，原 TOML 删除或损坏也可管理当前实例。restart 默认选择该固定路径，不沿用旧实例来源；预校验失败保留旧实例，不承诺停止后的配置冻结。

实例记录固定在项目根 .run，运维负责避免并发命令及意外多实例：

```text
.run/
├── instance.json   # 格式 3；PID、系统启动时间、配置、地址、日志、停止期限
└── console.log     # 后台输出和启动诊断
```

运行文件为 0600，Shell 使用 stat 检查所有者与权限，拒绝符号链接，jq 校验格式 3 记录，并通过 instance.json.pending 原子替换。登记发生在 exec 前，Shell 与 Uvicorn 的 PID/系统启动时间保持一致。身份只核对 PID 和启动时间，停止前核对后发 SIGINT，检查与信号间仍有 PID 复用竞态。旧格式记录拒绝控制。

后台使用 nohup 忽略 SIGHUP，标准输入为 /dev/null，输出追加到 console.log；不再通过 Python 创建独立会话。启动与停止等待使用 Shell 自有 sleep 计时进程，支持配置中的小数秒，命令退出时清理计时进程。Shell 通过 cli.py 的 export-service-settings 预校验配置，Python 不登记实例、查询进程或发送信号；service.py 与 service_control.py 已删除。

不创建 control.lock 或 run.lock，没有服务锁或锁描述符交接，并发调用不会被串行化。正常退出可以留下记录，后续按 PID 和启动时间判断存活；stop 等待原目标退出后清理匹配记录，文件消失不会使等待提前成功。进程查询失败时返回错误，保留匹配记录，不把查询错误当成已退出或继续重启。记录丢失或并发启停可能导致重复启动，由运维控制。数据库维护锁保持不变，但不能替代项目级实例发现。健康仍验证监听归属、HTTP 200 和预期 JSON。

管理成功为 0，status 已停止 3，参数错误 2，其他错误 1，管理命令中断仍为 130/143。前台 run 透传 Uvicorn 原生退出结果，不再统一转换 SIGINT/SIGTERM；当前锁定版本在服务运行后接收 SIGINT 可返回 0，SIGTERM 按原生信号结束（Shell 中为 143）。lifespan 启动失败仍可返回 3。不注册自定义信号或 atexit 收尾，不额外保证最后几条 Uvicorn 日志排空；lifespan 的应用资源清理保持不变。停止失败或中断不继续重启，查询中断不停止既有实例，后台启动回收只针对本次新建进程。

Shell 的启停预算取自 TOML 的 service 分组。停止现有实例时使用记录保存的预算，该预算独立于 Uvicorn 的 10 秒优雅关闭等待。应用日志仍取 TOML logging，数据库维护锁机制不变，详见[配置约定](docs/configuration.md)和[数据库指南](docs/database.md)。

## 可选 Vite 开发

先停止服务，将 `configs/app.toml` 中的 `serve_frontend` 设为 `false`，再分别在两个终端执行：

```bash
# 终端一
sh entrypoints/service.sh run
# 终端二
pnpm --dir frontend dev
```

随附配置访问 [http://127.0.0.1:5173/](http://127.0.0.1:5173/)。修改端口时同步 `vite.proxy_target` 与 `allowed_origins`；切回单服务模式时恢复 `serve_frontend = true`，重新构建并重启。

## 数据库与备份

升级、恢复或切换日常数据库前先停止服务，并确认其他数据库使用者也已停止。已有库需要升级前快照时，在新增或引入 revision **之前**，使用与旧库版本匹配的代码执行：

```bash
uv run --directory backend python -m entrypoints.cli db-backup
```

备份写入配置中的 `backup_directory`，校验后打印路径，不覆盖已有文件。不要只复制运行中的 SQLite 主文件，也不要删除活动的 WAL/SHM。完整备份、恢复及停服升级流程见[数据库指南](docs/database.md)。

### 迁移生成、审查与验证

模型变更与 Alembic revision 一同维护，已交付并执行过的迁移保持不变。候选迁移与临时库检查使用：

```bash
uv run --directory backend python -m entrypoints.cli db-revision -m "describe schema change"
uv run --directory backend python -m entrypoints.cli db-check
```

两者使用隔离临时库；`db-check` 不证明旧数据转换正确，也不检查日常库漂移。生成、审查、旧数据回归和显式应用的完整顺序见[迁移流程](docs/database.md#迁移生成审查与验证)。

## 接口类型与验证

命令从项目根目录执行，先安装前后端依赖。OpenAPI 导出不启动服务、不连接数据库；类型由生成器维护，检查模式不改写文件。

```bash
pnpm --dir frontend api:types
pnpm --dir frontend api:types:check
uv run --directory backend ruff check --config pyproject.toml . ../scripts/create_project.py
uv run --directory backend ruff format --check --config pyproject.toml . ../scripts/create_project.py
uv run --directory backend python -m entrypoints.cli db-check
uv run --directory backend pytest
pnpm --dir frontend format:check
pnpm --dir frontend lint
pnpm --dir frontend typecheck
pnpm --dir frontend build
```

按变更范围选择检查。Ruff 覆盖后端与项目创建器，`build` 包含 TypeScript 检查；Python 格式整理使用 `ruff format`，接口类型通过生成器维护。

`pnpm --dir frontend format:check` 统一检查前端文件、根 README、`docs/` 下全部 Markdown 和各级 `AGENTS.md`，新增子目录自动纳入；`pnpm --dir frontend format` 整理相同范围。两者共用根 `.prettierrc.toml`，并读取根 `.prettierignore` 和 `.gitignore`，排除生成类型、锁文件、依赖、构建和私有运行产物。

后端服务测试使用独立临时项目副本，隔离项目 `.run/`，其余测试使用临时 TOML、日志和 SQLite；`integration` 测试需要本机监听与信号权限，受限环境可运行 `uv run --directory backend pytest -m 'not integration'`，但需另报未验证的真实启停。上面的 `build` 使用主 TOML 的输出位置；需要隔离验证构建时，使用下面的 E2E 入口，它也执行 TypeScript 检查与构建。

```bash
pnpm --dir frontend exec playwright install chromium
pnpm --dir frontend test:e2e
```

E2E 经 test:e2e 执行 TypeScript 检查、临时生产构建、数据库升级和 Chromium 流程，通过临时项目的 Shell 入口启动服务，不复用日常状态或产物。正常结束发送 SIGINT，使用 Uvicorn 原生停止并等待进程退出，不额外保证最终日志排空。后端测试辅助器超时不强杀；E2E 运行器仅对自有临时进程保留最终 SIGKILL 回收例外，超时必须失败并保留诊断。

可加 `--config /absolute/path/app.test.toml` 提供完整测试设置；成功且 `testing.keep_artifacts = false` 时清理，设为 true 或失败时保留并打印产物位置。不要直接执行 Playwright test 绕过隔离入口；Chromium 的本机进程权限不足时报告验证限制。

## 替换 Hello 示例

后端示例位于 `backend/app/` 下的 `routers/hello.py`、`services/hello.py`、`schemas/hello.py`，前端示例位于 `frontend/src/` 下的 `pages/WelcomePage.tsx` 与 `components/ConnectionStatus.tsx`。按[当前设计](docs/design.md#后端职责与数据库)划分业务类、依赖工厂与响应映射；在 `backend/app/application.py` 注册业务路由，新增持久化模型时同步迁移、生成类型和测试，并按业务调整各级 `AGENTS.md`。
