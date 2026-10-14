from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from paper_manage.db.base import Base
from paper_manage.models.associations import paper_tags

if TYPE_CHECKING:
    from paper_manage.models.paper import Paper


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)

    papers: Mapped[list["Paper"]] = relationship(
        secondary=paper_tags,
        back_populates="tags",
    )
