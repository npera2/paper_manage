from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from paper_manage.db.base import Base
from paper_manage.models.associations import paper_authors, paper_tags

if TYPE_CHECKING:
    from paper_manage.models.author import Author
    from paper_manage.models.tag import Tag


class Paper(Base):
    __tablename__ = "papers"

    # 标题模糊查询用的 GIN 索引（做 EXPLAIN 优化时加的，见迁移 e312e989a0f9）。
    #
    # 它**必须**声明在这里，不能只存在于迁移文件里。理由是：
    #   1. Alembic 的 autogenerate 是拿「模型 metadata」和「真实数据库」做 diff 的。
    #      索引只在库里、不在 metadata 里，它就会被判定成"多出来的东西"，
    #      于是生成一个删掉它的迁移 —— 静默地把性能优化撤销掉，而且看起来完全正常。
    #   2. 模型的 metadata 应该是 schema 的唯一可信来源。靠"记得手工执行过某句 SQL"
    #      来维持 schema，迟早会漏。
    # 代价：这里有三个 PostgreSQL 专有参数，换数据库就得改（这是有意的取舍）。
    __table_args__ = (
        Index(
            "ix_papers_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    abstract: Mapped[str | None] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer, index=True)
    venue: Mapped[str | None] = mapped_column(String(256))
    doi: Mapped[str | None] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    authors: Mapped[list["Author"]] = relationship(
        secondary=paper_authors,
        back_populates="papers",
    )
    tags: Mapped[list["Tag"]] = relationship(
        secondary=paper_tags,
        back_populates="papers",
    )
