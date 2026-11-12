# 数据库维护与迁移

本指南保存本脚手架的备份、恢复与迁移操作流程。命令均从项目根目录运行，并先安装后端依赖。配置字段见[配置约定](configuration.md)，检查命令总入口见 [README](../README.md#接口类型与验证)。

## SQLite 版本要求

Python 实际链接的 SQLite 至少为 3.51.3；本脚手架对 WAL 和 DELETE 统一使用这条完整性基线，不按发行版回补补丁放宽版本号。原因是 [WAL-reset 数据损坏修复](https://sqlite.org/wal.html#walresetbug)，并非 WAL 功能的首次支持版本。

检查 Python 使用的库，而非系统 `sqlite3` 命令版本：

```bash
uv run --directory backend python -c 'import sqlite3; print(sqlite3.sqlite_version)'
```

版本不足时，安装链接到 SQLite 3.51.3+ 的 Python 3.14 构建，再用 uv 重建后端虚拟环境；仅更新 SQLite 命令行程序不会改变 Python 链接的库。

## 数据库与备份

随附配置的数据库位于项目根目录的 `.data/app.sqlite3`，备份目录为 `.data/backups/`；连接开启 WAL、外键、保守持久化设置和有限锁等待。初始迁移只有 `alembic_version`，没有业务表。`.data/` 是运行数据目录，保持 Git 忽略。

需要升级前快照时，在修改迁移历史或切换到含新迁移的代码之前，用与当前库版本匹配的代码停服并执行备份；新建空库跳过备份。迁移审查与验证完成后，再显式升级并启动。`db-upgrade` 与应用 lifespan 持有同一个数据库锁，服务运行时会拒绝迁移。执行维护前，在服务终端按 Ctrl+C 停止，并确认其他数据库使用者也已停止；文件锁仅约束使用同一锁机制的本机进程。

```bash
# 已有库按需备份：在新增 revision 或切换代码之前执行；新建空库跳过
# 在服务终端按 Ctrl+C 停止
uv run --directory backend python -m entrypoints.cli db-backup

# 完成迁移生成、审查与验证后，确认所有数据库使用者均已停止
# 在服务终端按 Ctrl+C 停止
uv run --directory backend python -m entrypoints.cli db-upgrade
sh backend/entrypoints/service.sh
```

维护命令与服务必须使用同一个配置文件。备份通过 SQLite Backup API 创建一致性快照，校验完整性与版本后打印路径，保存到 `backup_directory` 指定的位置，不覆盖旧文件。`db-backup` 要求库版本与所用代码一致；生成新 revision 后，不能用新代码备份仍停留在旧 revision 的库，应使用此前与库版本匹配的代码创建快照。

`db-backup` 不自动停服，也不持有服务/升级操作锁；停服是操作者需要完成的前提，不能从命令成功推断服务已停止。

恢复时先停止服务并按需备份当前数据库。校验候选快照完整性、版本和记录后，复制到新的数据目录，文件名与 `database_filename` 一致；修改配置文件的 `data_dir` 指向副本，审查并执行必要迁移后再启动。保留原库，确认恢复成功后再处理旧文件。

不要在应用运行时只复制主数据库作为备份，也不要手工删除活动的 WAL/SHM 文件。

## 迁移生成、审查与验证

迁移环境、操作入口和版本脚本统一位于 `backend/migrations/`：`operations.py` 提供 Alembic 配置、head 查询和显式升级，`env.py` 负责异步执行环境，`development.py` 负责生成和检查，`versions/` 保存版本历史。迁移文件与模型变更一起交付。已交付并执行过的迁移保持不变，后续修正新增 revision；初始 `0001_baseline` 仍不创建业务表。以下命令从项目根目录运行，先安装后端依赖。

| 命令                            | 数据库目标与结果                                                                                         |
| ------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `db-revision -m "说明"`         | 在独占临时库重放已有迁移，再比较模型，向 `backend/migrations/versions/` 写入候选迁移；没有差异时不写文件 |
| `db-revision --empty -m "说明"` | 重放已有迁移后生成手写模板，适用于数据回填及自动比较无法识别的结构变化                                   |
| `db-check`                      | 在独占临时库执行 `base → head`，再检查模型是否存在遗漏的迁移；不生成 revision，失败时返回非零退出码      |
| `db-upgrade`                    | 显式升级所选 TOML 对应的应用数据库，沿用停服和操作锁要求                                                 |

`db-revision` 与 `db-check` 从完整 TOML 读取并校验设置，在 `testing.temporary_directory` 下创建独占子目录，强制隔离数据、备份、日志和前端输出路径，不连接日常数据库或操作日常服务。临时子目录成功或失败后均清理；已有迁移脚本必须只处理数据库，不调用外部服务或自行访问其他运行路径。这些命令运行可信 Python 迁移代码，不提供脚本沙箱。自定义配置使用 `uv run --directory backend python -m entrypoints.cli --config /absolute/path/app.local.toml db-check`，`--config` 放在子命令前。

### 1. 按需备份已有库

在新增或引入 revision 之前，按上方“数据库与备份”的命令停服并执行 `db-backup`，确认成功后保留打印的快照路径。此时库与代码的迁移版本仍匹配；新建空库跳过这一步。

### 2. 修改并导出模型

在 `backend/app/models/` 定义模型，并确保其模块由 `models/__init__.py` 导入，使所有表进入 `Base.metadata`。漏导入可能被识别为删表，必须审查。

### 3. 生成候选迁移

命令从迁移历史重建比较基线，无需先升级日常库；一次完成一份候选迁移的审查，避免并发生成。

```bash
uv run --directory backend python -m entrypoints.cli db-revision -m "add records"
```

对纯数据迁移、CHECK 表达式等未被检测的变化，显式创建手写模板并补全操作；模板中的 `pass` 不代表任务完成：

```bash
uv run --directory backend python -m entrypoints.cli db-revision --empty -m "backfill record labels"
```

### 4. 审查实际操作和版本链

确认 `down_revision` 指向预期前序、仓库只有一个 head，逐项核对以下内容。生成命令与检查命令发现多个 head 时拒绝继续；先审查分叉来源和迁移顺序，不通过 `stamp` 掩盖问题。

- 重命名是否被错误生成为删列/加列或删表/建表；旧值如何保留。
- 非空、唯一、类型及默认值变化对旧记录的影响；需要时先增加兼容结构、回填并验证，再施加约束。
- SQLite batch 重建涉及的索引、命名约束、CHECK 和已有关系是否保留。当前自动比较启用类型比较，未启用服务端默认值比较；CHECK 等变化不能只依赖自动生成和 `db-check`。
- 数据迁移使用 revision 内定义的 SQL/表结构及 Alembic 连接，避免导入未来会变化的应用 ORM 模型或业务服务。
- `downgrade()` 的真实能力。删列、回填及其他有损转换不能承诺恢复原数据；明确拒绝不支持的降级，并说明快照恢复路径。

以下两个 Alembic 原生命令只查看脚本历史；建库、升级和开发检查使用应用 CLI，以保留 TOML 与隔离边界：

```bash
uv run --directory backend alembic heads
uv run --directory backend alembic history
```

生成文件也要通过 Python 静态检查。下面的示例文件名需替换为生成命令打印的实际新文件；只整理这份候选迁移，避免改写已交付的历史文件：

```bash
migration_file='migrations/versions/0123456789ab_add_records.py'
uv run --directory backend ruff check --fix --config pyproject.toml "$migration_file"
uv run --directory backend ruff format --config pyproject.toml "$migration_file"
```

### 5. 验证空库和旧数据两条路径

先运行迁移检查和相关测试，再按 [README 的验证命令](../README.md#接口类型与验证)完成后端检查：

```bash
uv run --directory backend python -m entrypoints.cli db-check
uv run --directory backend pytest tests/test_migrations.py tests/test_database.py
```

`db-check` 证明当前环境能从空库重放迁移，并且在 Alembic 的比较能力内与模型一致；它不检查日常库的实际漂移，也不能证明旧数据转换、所有约束或降级正确。`tests/test_migrations.py` 的合成流程使用独立的测试 revision 和 metadata，分别覆盖只有测试基线、已有后续业务 revision 的情况；真实迁移历史由单独的重放和 CLI 测试验证。baseline 无业务表测试只执行到真实 `0001_baseline`，不随 head 增长。新增业务迁移仍需添加自身的升级回归测试，SQLite batch 重命名和回填示例可供参考：

- 用临时 TOML 和独占 SQLite，将数据库迁移到实际前序 revision，再插入该版本的代表性记录，包括空值、边界值及冲突候选。
- 执行新迁移，断言旧记录的标识、数量、关键值、回填结果和新约束符合预期，并核对版本；重复升级不应重复转换记录。
- 对声明支持的降级，仅在临时库验证；有损或不可降级的迁移明确记录限制，不能把 schema 降级当作原数据恢复。

### 6. 应用到日常库

审查和测试完成后，按上方“数据库与备份”的流程再次确认停服，显式升级并启动。升级前快照已在步骤 1 准备；恢复按上方的快照校验与副本数据目录流程执行。

官方能力边界见 [Alembic 自动生成说明](https://alembic.sqlalchemy.org/en/latest/autogenerate.html#what-does-autogenerate-detect-and-what-does-it-not-detect) 和 [SQLite batch migration](https://alembic.sqlalchemy.org/en/latest/batch.html)。

## 异步数据库调用约定

数据库使用 `sqlite+aiosqlite` 和 `AsyncEngine`。应用生命周期中创建 `async_sessionmaker`，每个请求通过异步依赖获得独立的 `AsyncSession`，关闭应用时 `await engine.dispose()`。

含数据库 I/O 的 Router、Service 和 DAO 使用 `async def`，通过 `await session.execute()`、`await session.flush()` 等访问数据库。写入事务由 Service 使用 `async with session.begin()` 管理，成功提交、失败回滚。纯计算的 Hello Service 可以继续使用普通函数。

不要跨并发任务共享 AsyncSession，也不要将未加载的 ORM 关系交给响应序列化触发隐式 I/O。SQLite 连接使用 SQLAlchemy 官方事件方式显式发出 BEGIN，保留外键、WAL 和事务完整性。

Alembic 的命令入口仍是维护 CLI：`migrations/operations.py` 负责配置、版本 head 与显式升级，迁移环境创建异步引擎，通过 `AsyncConnection.run_sync()` 将 Alembic 的同步 DDL API 桥接到异步驱动；不要在应用请求内自动升级数据库。同步测试准备可以调用 `migrations.operations.upgrade_database()`，异步测试通过线程边界调用该同步维护入口。需要验证特定旧版本时，在独占临时库使用同模块的 `migration_config()` 构造配置，再显式调用 Alembic 的目标 revision 升级。

备份实现在 `backend/app/maintenance/backup.py`，使用 `DatabaseBackup` 类接收配置依赖并调用 aiosqlite 的异步 Backup API；CLI 负责参数、对象组装和事件循环。取消时等待已经提交的复制完成再关闭目标连接、删除未返回的快照，并继续传播取消，不重新发起复制。

`database.synchronous` 是 SQLite 的持久化级别，与 SQLAlchemy 的同步/异步调用方式无关。异步驱动使用相同的 SQLite 文件格式，不需要另建数据库或切换迁移版本。

## 模型约束与命名

索引与唯一约束的自动名称包含全部列。同一组列上的多个条件索引或表达式索引应显式命名。CheckConstraint 支持未命名建表；需要后续迁移管理时，应从首次定义起使用明确名称，例如 `CheckConstraint("quantity > 0", name="ck_items_positive_quantity")`。Alembic 的 autogenerate 不完整覆盖 CHECK 变更，必须人工审查和补齐迁移。
