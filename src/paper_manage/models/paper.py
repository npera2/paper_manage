from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from paper_manage.db.base import Base
from paper_manage.models.associations import paper_authors, paper_tags

if TYPE_CHECKING:
    from paper_manage.models.author import Author
    from paper_manage.models.tag import Tag


class Paper(Base):
    __tablename__ = "papers"

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
