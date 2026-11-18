# 项目创建工具规则

适用于 `scripts/`；同时遵循[根目录规则](../AGENTS.md)。使用方式见[项目创建指南](../docs/project-creation.md)；生成项目的 README 会移除模板创建教程，创建器与指南仍保留。

## 创建与复制边界

- `create-project.sh` 是创建入口，`create_project.py` 使用 Python 标准库与 rsync；创建阶段不要求应用依赖，不增加 FastAPI/Pydantic 导入。Python 版本取 `backend/.python-version`。
- 项目名、目标目录与后端端口必须显式提供；Vite 端口省略时继承模板 `frontend/configs/vite.toml` 的显式值。目标是脚手架之外、尚不存在的最终目录，相对目标从调用方工作目录解析，不再附加项目名；文件和符号链接同样不得覆盖。
- 复用 `backend/app/utils/path_safety.py` 的标准库路径策略，不能另写一套较弱校验。模板的数据、备份、日志和前端输出须位于模板内；私有目录避开源码、依赖与公开输出，公开输出额外避开遗留运行目录。默认 `.data/` 与 `logs/` 可用于私有数据，内部绝对路径在副本转为相对路径，不能指回模板；测试临时父目录可在模板外。
- 依据 .gitignore 与实际运行路径排除数据、备份、日志、状态、依赖、缓存、构建及私有配置，固定排除根 .run、.git、.env* 和 .secrets*，副本补齐 /.run/ 忽略规则。保留源码、迁移、文档、规则和锁文件，拒绝复制后指向副本外部的符号链接；不读取、复制或生成 .env。
- 复制前校验创建依赖的关键字段和路径，复制后检查必要文件与源树完整性。根 entrypoints 只允许普通 service.sh，拒绝独立启动脚本、Python 文件、其他文件或子目录；service.sh 和后端 entrypoints/api.py 必需，纳入源树及路径保护。后端 Python 实现仍从 backend 运行，复制时显式排除旧 backend/entrypoints/service.sh，源树检查同步忽略旧路径。根 .prettierrc.toml 与 .prettierignore 同样必需并原样复制。完整 Pydantic 语义校验由生成项目导出、测试或首次启动完成，不宣称创建器已完成全部应用校验。
- 只修改本次新目标；失败只清理本次创建的目标目录，不影响模板、已有目标或服务，不做依赖安装、建库、构建、Git 初始化或服务启动。

## 重命名与验证

- 同步应用标题、包名、后端/Vite 端口、代理和允许来源。生成副本的后端监听端口写入 service.sh 的 server_port，Vite 端口与代理目标写入 `frontend/configs/vite.toml`，允许来源写入 `configs/app.toml`。保留模板文件和其余配置值及注释，创建阶段只校验联动所需字段。
- `uv.lock` 只重命名本地虚拟项目并执行离线锁检查；第三方版本、哈希与前端锁文件保持不变，不重新解析或升级依赖。
- 更新副本的项目文档并标明继承历史证据的来源，不把模板验证当作新项目验证；新增 AGENTS 内容优先使用相对路径和工具版本文件，避免复制后留下模板绝对路径或固定项目名。
- 修改创建或复制行为时，使用临时目标运行 `uv run --directory backend pytest tests/test_project_creation.py`，覆盖独立副本、带空格路径、已有目标拒绝、排除规则、失败清理、配置重写与锁文件保持；检查模板文件未变，不以生成成功代替应用运行验证。
- Python lint/格式使用后端 Ruff 配置，范围包括 `../scripts/create_project.py`；修改 sh 入口时再执行 `sh -n scripts/create-project.sh`。命令均从项目根目录运行。
