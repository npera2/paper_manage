from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from paper_manage.schemas.author import AuthorCreate, AuthorRead
from paper_manage.schemas.tag import TagRead

# 用户从浏览器地址栏复制的 DOI 常带这些前缀，统一剥掉再存
DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:")
CURRENT_YEAR = datetime.now().year

# 标签名的长度上限，对应 Tag.name 的 String(64)。
# 不在这一层挡住的话，超长标签会一路走到数据库才报错，
# 变成 500（服务端错误）而不是干净的 422（客户端错误）。
TagName = Annotated[str, Field(max_length=64)]


def _normalize_doi(value: object) -> object:
    """剥掉 URL 前缀、转小写。两个模型共用，所以抽成模块级函数。"""
    if not isinstance(value, str):
        return value

    cleaned = value.strip()
    lowered = cleaned.lower()
    for prefix in DOI_PREFIXES:
        if lowered.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
            break
    return cleaned.strip().lower()


def _clean_tags(value: list[str]) -> list[str]:
    """标签去空白、丢空串、去重（保留第一次出现的顺序）。"""
    seen: set[str] = set()
    result: list[str] = []
    for raw in value:
        name = raw.strip()
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


class PaperCreate(BaseModel):
    """POST /papers 的请求体。"""

    # str_strip_whitespace 和 min_length 要配合用：
    #   不加 strip，标题 "   " 能通过 min_length=1 的检查；
    #   加了 strip，"   " 先变成 ""，才会被 min_length=1 挡下。
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=512)
    abstract: str | None = None
    year: int | None = Field(default=None, ge=1000, le=2100)
    venue: str | None = Field(default=None, max_length=256)
    doi: str | None = Field(default=None, max_length=128)
    authors: list[AuthorCreate] = Field(default_factory=list)
    tags: list[TagName] = Field(default_factory=list)

    @field_validator("doi", mode="before")
    @classmethod
    def normalize_doi(cls, value: object) -> object:
        """把 DOI 归一成裸串。

        mode="before" 表示在类型校验之前先跑，这时拿到的是原始输入。
        为什么放在 schema 层而不是 crud 层：规范化属于「数据入口卫生」，
        应该在系统边界一次做完，下游就可以无条件信任数据。
        """
        return _normalize_doi(value)

    @field_validator("year")
    @classmethod
    def year_not_in_future(cls, value: int | None) -> int | None:
        """年份不能太离谱。预印本可能提前一年，所以放宽到明年。"""
        if value is not None and value > CURRENT_YEAR + 1:
            raise ValueError(f"year 不能晚于 {CURRENT_YEAR + 1}")
        return value

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, value: list[str]) -> list[str]:
        return _clean_tags(value)

    @field_validator("authors")
    @classmethod
    def dedupe_authors(cls, value: list[AuthorCreate]) -> list[AuthorCreate]:
        """同一位作者在同一篇论文里只保留一次，保留首次出现的顺序。

        这不是"好看"的问题：paper_authors 是 (paper_id, author_id) 复合主键，
        重复作者会插出重复关联行，直接撞主键约束报 IntegrityError。
        AuthorCreate 已经用 str_strip_whitespace 去掉了名字两端空白，
        所以这里可以直接按名字比较。
        """
        seen: set[str] = set()
        result: list[AuthorCreate] = []
        for item in value:
            if item.name not in seen:
                seen.add(item.name)
                result.append(item)
        return result


class PaperUpdate(BaseModel):
    """PATCH /papers/{id} 的请求体，所有字段可选。

    注意区分「没传这个字段」和「明确传了 null」：
    配合 crud 层的 model_dump(exclude_unset=True)，前者不改、后者才置空。
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=512)
    abstract: str | None = None
    year: int | None = Field(default=None, ge=1000, le=2100)
    venue: str | None = Field(default=None, max_length=256)
    doi: str | None = Field(default=None, max_length=128)
    tags: list[TagName] | None = None

    @field_validator("doi", mode="before")
    @classmethod
    def normalize_doi(cls, value: object) -> object:
        return _normalize_doi(value)

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _clean_tags(value)

    @model_validator(mode="after")
    def reject_empty_patch(self) -> Self:
        """拒绝空 PATCH。

        model_validator(mode="after") 在所有单字段校验通过之后运行，
        这时能看到完整对象 —— 所以跨字段、跨整体的规则只能用 model_validator。

        model_fields_set 是「请求体里真正出现过的字段名集合」，
        body 是 {} 时它是空的。

        别小看这条规则：没有它，PATCH {} 会静默成功、什么都不改，
        调用方以为自己改了什么，排查起来非常崩溃。
        """
        if not self.model_fields_set:
            raise ValueError("至少要提供一个要修改的字段")
        return self


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
