"""add pg_trgm index on papers title

Revision ID: e312e989a0f9
Revises: a83c3181c4dc
Create Date: 2026-10-14 21:45:24.013161

这个迁移把之前手工敲在 psql 里的两句 SQL 固化成正式迁移：

    CREATE EXTENSION pg_trgm;
    CREATE INDEX ix_papers_title_trgm ON papers USING gin (title gin_trgm_ops);

为什么必须固化：手工执行的 SQL 没有任何记录留存。结果是
测试库（用 create_all 建的）和开发库 schema 不一致，
CI 里更不会有人记得去补这一句，而少了它标题模糊查询会退化成全表扫描 ——
性能问题不报错，只会悄悄变慢。

迁移文件是 schema 的唯一可信来源。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e312e989a0f9"
down_revision: str | None = "a83c3181c4dc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 扩展必须先于索引创建：gin_trgm_ops 这个操作符类由 pg_trgm 提供
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_index(
        "ix_papers_title_trgm",
        "papers",
        ["title"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_papers_title_trgm", table_name="papers")
    # 有意不删扩展：可能还有别的对象在用它，而且删扩展的影响面
    # 超出了本次迁移的范围。downgrade 只应撤销自己做的事，不做连带破坏。
