from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from paper_manage.db.base import Base
from paper_manage.models.associations import paper_authors

if TYPE_CHECKING:
    from paper_manage.models.paper import Paper


class Author(Base):
    __tablename__ = "authors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(256), index=True)
    affiliation: Mapped[str | None] = mapped_column(String(256))

    papers: Mapped[list["Paper"]] = relationship(
        secondary=paper_authors,
        back_populates="authors",
    )
