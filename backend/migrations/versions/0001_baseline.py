"""建立受版本管理的数据库，不为 Hello 示例额外创建业务表。"""

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
