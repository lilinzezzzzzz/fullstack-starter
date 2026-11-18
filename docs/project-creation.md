# 基于脚手架创建新项目

本指南用于从当前模板创建独立的新项目。调整正在开发的项目时，使用[已有项目架构对齐指南](project-alignment.md)。以下创建命令从模板根目录执行，生成后切换到新项目根目录。

## 1. 用脚本生成

在 macOS/Linux 上准备 uv 和 rsync。脚本使用 `backend/.python-version` 固定的 Python 标准库，创建阶段不要求先安装应用依赖；Python 尚未安装时由 uv 准备。

在脚手架根目录执行：

```bash
sh scripts/create-project.sh \
  --name my-app \
  --target-dir /absolute/path/to/my-app \
  --port 18002 \
  --vite-port 5174
```

也可以从其他工作目录使用脚本的绝对路径调用。`--target-dir` 是新项目的最终目录，不会再自动追加项目名；相对路径以调用时的工作目录解析。目录名可以与项目标识不同，含空格时加引号。

| 参数           | 要求与含义                                                                      |
| -------------- | ------------------------------------------------------------------------------- |
| `--name`       | 必填；1–63 位小写英文字母、数字和连字符，以字母开头，连字符不能连续或位于末尾   |
| `--target-dir` | 必填；最终目标目录，必须尚不存在且位于脚手架目录之外，缺失的父目录会创建        |
| `--port`       | 必填；新项目后端端口，范围 1–65535                                              |
| `--vite-port`  | 可选；省略时继承模板 `frontend/configs/vite.toml` 的 `port`，必须与后端端口不同 |
| `--help`       | 查看参数说明                                                                    |

脚本校验参数和目标目录；端口是否已被占用在服务实际启动时检查，不预留端口或处理占用端口的进程。

## 2. 自动完成的调整

- 复制源码、迁移、规则、文档、生成类型和两份锁文件；依据 `.gitignore` 排除数据、备份、日志、PID、依赖、缓存、构建产物和本地配置，并固定排除项目根 `.run/`、`.git`、私有 `.env*` 与 `.secrets*`；不读取或生成 .env。
- 额外排除 TOML 指定的实际运行路径，并将新项目的运行路径补入副本 `.gitignore`，支持模板内的自定义目录。数据、备份、日志和前端输出路径必须在模板目录内；内部绝对路径会改为相对路径，避免指向原项目。模板外的这些路径会明确报错，需先调整模板配置。
- 复制前复用应用的源码路径保护规则，并校验创建所需的关键字段；复制后按源文件树检查 API、路由、服务、迁移、sh 脚本、前端入口和项目元信息；缺少文件时创建失败，不报告成功。
- 将后端项目名改为 `my-app-backend`，前端包名改为 `my-app-frontend`，应用标题改为 `my-app`。
- `--port` 重写生成副本 service.sh 的 server_port 整数常量，并同步 `frontend/configs/vite.toml` 的 `port` 和 `proxy_target`，以及 `configs/app.toml` 中对应的 `allowed_origins`。其余配置继承模板，保留 TOML 注释。
- 只更新 `uv.lock` 中本地虚拟项目的名称，并用 `uv lock --check --offline` 校验；第三方依赖版本、哈希和前端锁文件保持不变，创建时无需重新解析依赖源。
- 更新新项目 README、设计文档中的项目名称和端口，为继承的验证记录注明来源。应用标题与版本作为元信息注入前端；Hello API 和页面欢迎语仍为固定示例，不随项目名称变化。

创建器重写 README、根 AGENTS、设计与配置文档；其余指南及子目录 AGENTS 按原文复制，通用示例中的项目名与端口不自动替换。实际操作始终以副本 service.sh 的固定端口、TOML 和版本文件为准。

目标目录已存在（包括文件或符号链接）时直接拒绝覆盖；复制或配置调整失败时，清理本次新建的目标目录。sh 入口调用 [scripts/create_project.py](../scripts/create_project.py) 处理结构化数据，仅依赖 Python 标准库和 rsync。

创建器校验路径、源文件完整性，以及创建过程依赖的关键字段。生成项目的 `export-settings`、测试或首次启动执行完整的 Python 配置校验。Vite 开发配置的完整校验在生成项目执行 `pnpm --dir frontend dev` 时完成。

根 entrypoints/service.sh 与后端 api.py、cli.py、`entrypoints/__init__.py`、app/application.py、app/telemetry/adapter.py、app/utils/lazy_proxy.py 等文件必需，不再需要 service.py 或 service_control.py。配置代理工具或 telemetry 适配文件缺失时创建失败；它们与其他源码一起复制，不依赖外部项目。服务装配集中在 application.py，Shell 所需配置由 cli.py 的 export-service-settings 导出。根 entrypoints 只允许普通 service.sh，其他文件或子目录会导致生成失败；复制仍排除旧 backend/entrypoints/service.sh。运行需要 jq、ps、stat、lsof、curl、nohup 等本机工具，源树检查不代替运行验证。

根目录的 `.prettierrc.toml` 与 `.prettierignore` 同属必需文件，原样复制到新项目根目录，并纳入源码路径保护，不能作为构建输出或私有运行目录。新项目的前端命令、README、`docs/` 与各级 AGENTS 共用这份配置，忽略路径相对于新项目根目录；检查与整理仍使用 README 中的统一命令。

创建完成后会打印后续命令。固定 .run 的排除不依赖模板 .gitignore 或记录是否完整，新项目补齐 /.run/ 忽略规则；记录、控制台和旧版本锁文件均不继承。服务管理不再创建锁，运维负责串行调用五个命令。新项目从空数据库开始，依赖、建库、构建、Git 和服务分别准备；原项目的数据与服务不受创建操作影响。

## 3. 安装、验证与运行

切换到新项目目录，按照其 [README 的首次运行步骤](../README.md#首次运行)安装依赖、检查并创建空库、构建和启动。Node.js、pnpm 和 Python 版本以项目中的版本文件及包元信息为准。

```bash
cd /absolute/path/to/my-app
```

依赖安装后，可按 [README 的验证命令](../README.md#接口类型与验证)检查代码和接口类型；后端测试使用临时 TOML、数据库和日志，不依赖新项目的日常库。配置与创建器回归会核对元信息、端口和来源；浏览器验证结果须由新项目自己运行后记录。

本例后端端口为 `18002`，打开 `http://127.0.0.1:18002/`；Hello API 的 `/api/v1/hello` 应返回 `{"message": "Hello World"}`，健康检查 `/api/health` 应显示数据库正常。实际访问地址取新项目 service.sh 的端口常量，数据与日志路径仍取 TOML，前台 `run` 查看完成后按 Ctrl+C 停止；后台 `start` 则使用同一配置执行 `sh entrypoints/service.sh stop`。

需要热更新时，按 [README 的 Vite 步骤](../README.md#可选-vite-开发)将 `serve_frontend` 设为 `false`；本例 Vite 端口为 `5174`，其余步骤相同。

## 4. 建立版本库并开始业务开发

需要独立版本管理时，在新项目根目录执行：

```bash
git init
git status --short --untracked-files=all
```

先检查待跟踪文件，再进行首次提交。新项目维护自己的 Git 历史和锁文件；复制后的代码与脚手架独立，后续升级需选择性迁移并重新验证。

新项目仍以 Hello 页面起步。按实际业务更新 README、设计文档和 AGENTS 约束，再按 [README 的业务开发入口](../README.md#替换-hello-示例)增加业务代码、Alembic 迁移、接口类型与测试。继承的历史验证只代表模板，新项目自己的验证结果另行记录。
