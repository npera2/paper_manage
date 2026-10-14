from pydantic import BaseModel, Field


class BibtexImportRequest(BaseModel):
    """把 BibTeX 文本直接塞进请求体的格式。

    另一种入口是文件上传（POST /papers/import/upload），
    两者最终都走到同一个导入函数。
    """

    bibtex: str = Field(min_length=1, description="BibTeX 文本内容")


class ImportIssue(BaseModel):
    """一条导入问题的明细。

    为什么要把明细返回给用户，而不是只返回一个失败计数：
    批量导入最难受的体验是「有 3 条失败了，但不知道是哪 3 条」，
    用户只能一条条试。把原因原样告诉他，他才能去改源文件。
    """

    index: int | None = Field(
        default=None,
        description="第几条记录（从 1 开始）；解析级错误为 null",
    )
    key: str | None = Field(default=None, description="BibTeX 条目的引用键")
    reason: str = Field(description="失败原因")


class ImportStats(BaseModel):
    """导入结果统计。

    三个计数满足 total == created + skipped + failed，
    这个不变式在 service 层保证。
    """

    total: int = Field(description="解析出的条目总数")
    created: int = Field(description="新增的条数")
    skipped: int = Field(description="因为库里已存在而跳过的条数")
    failed: int = Field(description="校验或写入失败的条数")
    issues: list[ImportIssue] = Field(
        default_factory=list,
        description="失败与解析错误的明细（跳过的条目太正常了，不记在这里）",
    )
