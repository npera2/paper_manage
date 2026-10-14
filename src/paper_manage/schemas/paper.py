from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from paper_manage.schemas.author import AuthorCreate, AuthorRead
from paper_manage.schemas.tag import TagRead


class PaperCreate(BaseModel):
    """POST /papers 的请求体。

    字段约束在这里就挡住，不用等到数据库层才报错。
    """

    title: str = Field(min_length=1, max_length=512)
    abstract: str | None = None
    year: int | None = Field(default=None, ge=1000, le=2100)
    venue: str | None = Field(default=None, max_length=256)
    doi: str | None = Field(default=None, max_length=128)

    # 作者给完整信息（可能要新建）；标签只给名字（标签是受控词表，一般复用已有的）
    authors: list[AuthorCreate] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class PaperUpdate(BaseModel):
    """PATCH /papers/{id} 的请求体。

    所有字段都可选：只传你想改的字段。
    配合 crud 层的 model_dump(exclude_unset=True)，就能区分
    「没传这个字段」和「明确传了 null」——这是 PATCH 语义的关键。
    """

    title: str | None = Field(default=None, min_length=1, max_length=512)
    abstract: str | None = None
    year: int | None = Field(default=None, ge=1000, le=2100)
    venue: str | None = Field(default=None, max_length=256)
    doi: str | None = Field(default=None, max_length=128)
    tags: list[str] | None = None


class PaperRead(BaseModel):
    """论文的输出模型，作者和标签以嵌套对象返回。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    abstract: str | None
    year: int | None
    venue: str | None
    doi: str | None
    created_at: datetime
    authors: list[AuthorRead]
    tags: list[TagRead]


class PaperPage(BaseModel):
    """分页信封：总数和当页数据一起返回，前端才知道还有没有下一页。"""

    total: int
    limit: int
    offset: int
    items: list[PaperRead]
