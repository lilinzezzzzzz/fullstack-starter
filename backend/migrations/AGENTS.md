# 迁移规则

适用于 `backend/migrations/`；同时遵循[根目录规则](../../AGENTS.md)与[后端规则](../AGENTS.md)。操作流程见[数据库指南](../../docs/database.md#迁移生成审查与验证)。

## 历史与执行边界

- Alembic 环境、版本脚本、操作入口和开发工具集中于此。`operations.py` 管理配置、head 和显式升级，`development.py` 管理临时库重放、生成与检查，`env.py` 通过 AsyncConnection.run_sync 桥接 Alembic DDL；不增加独立同步运行时引擎。
- 持久化模型变更与迁移一同交付；模型模块必须经 `app/models/__init__.py` 导入，保证 Base.metadata 完整。缺失导入可能被误判为删表。
- 已交付并执行过的 revision 不改写，修正使用新 revision。`0001_baseline` 仅建立版本记录、不建业务表；检查 `down_revision` 与唯一 head，不用 stamp 掩盖分叉或版本不符。
- 迁移只通过 Alembic 连接处理数据库；数据迁移使用 revision 内定义的 SQL/表结构，不导入会演进的应用 ORM 或业务服务，不访问外部服务及其他运行路径。临时库隔离不等于 Python 脚本沙箱。
- autogenerate 只生成候选：人工审查删表/删列、重命名、非空/唯一/类型变化及 SQLite batch 重建后的索引与约束。当前比较覆盖类型、不覆盖服务端默认值，CHECK 等变更不能只依赖自动比较。
- 明确 downgrade 的能力。有损转换不得承诺恢复原数据，不支持的降级明确拒绝，并说明快照恢复路径。

## 开发与验证

从项目根目录运行，使用完整 TOML；自定义配置的 `--config` 放在子命令前。

```bash
uv run --directory backend python -m entrypoints.cli db-revision -m "describe schema change"
uv run --directory backend python -m entrypoints.cli db-check
uv run --directory backend pytest tests/test_migrations.py tests/test_database.py
uv run --directory backend alembic heads
uv run --directory backend alembic history
```

- `db-revision` 与 `db-check` 在配置指定的临时父目录创建独占资源，重放已有历史，成功或失败后都清理；不连接日常库。纯数据变更使用 `db-revision --empty -m "..."` 后补全，模板 pass 不是完成结果。不要并发生成候选迁移。
- `db-check` 只证明当前环境可从 base 重放到 head，并在比较能力内与模型一致；不能证明日常库无漂移、旧记录转换正确或降级无损。
- 新增迁移要用临时库从实际前序 revision 构造代表性旧记录，升级后验证数量、标识、关键值、回填与约束，再验证重复升级；声明支持的降级也在临时库验证。
- 保持真实历史测试与合成机制测试分离；baseline 空表断言只升级到真实 `0001_baseline`。不要为了新增业务迁移而删除基线断言或改写合成历史。
- `db-upgrade` 与 `db-backup` 操作所选 TOML 的真实应用数据库，不属于日常测试命令。已有库如需升级前快照，在引入新 revision 前用匹配旧库版本的代码停服备份；升级、恢复遵守授权与停服边界。
