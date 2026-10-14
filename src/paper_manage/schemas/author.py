from pydantic import BaseModel, ConfigDict, Field


class AuthorCreate(BaseModel):
    """创建论文时内嵌的作者信息（这位作者可能还不存在，要现场新建）。"""

    # str_strip_whitespace=True：自动去掉所有字符串字段两端的空白。
    # 这类「全局清洗」用 model_config 一次搞定，比给每个字段写 validator 省事。
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=256)
    affiliation: str | None = Field(default=None, max_length=256)


class AuthorRead(BaseModel):
    """作者的输出模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    affiliation: str | None = None
