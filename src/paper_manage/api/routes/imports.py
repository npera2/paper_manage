"""BibTeX 导入接口。

路径前缀是 /papers/import。注意它在 main.py 里必须挂在 papers 路由**之前**：
papers 有 /papers/{paper_id} 这个通配路径，如果它先注册，请求
/papers/import 会被它抢走、把 "import" 当成 paper_id 解析，直接 422。
规则：更具体的路径必须排在通配路径前面。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from paper_manage.api.deps import SessionDep, require_api_key
from paper_manage.schemas import BibtexImportRequest, ImportStats
from paper_manage.services import import_bibtex

router = APIRouter(prefix="/papers/import", tags=["imports"])


@router.post("", response_model=ImportStats, dependencies=[Depends(require_api_key)])
def import_from_text(payload: BibtexImportRequest, db: SessionDep) -> ImportStats:
    """从请求体里的 BibTeX 文本导入。

    返回 200 + 统计结果，而不是「有失败就报 4xx」。
    理由：这个请求本身是被正确处理了的，每条记录的结果属于**数据**，
    不属于 HTTP 层面的错误。前端看 stats.failed 决定怎么提示用户。
    """
    return import_bibtex(db, payload.bibtex)


@router.post(
    "/upload",
    response_model=ImportStats,
    dependencies=[Depends(require_api_key)],
)
def import_from_file(
    db: SessionDep,
    file: Annotated[UploadFile, File(description=".bib 文件")],
) -> ImportStats:
    """从上传的 .bib 文件导入。

    这里故意用同步的 `def` 而不是 `async def`：
    我们的数据库访问是同步的（同步 SQLAlchemy Session）。
    同步 def 的接口 FastAPI 会丢到线程池里跑，不会卡住事件循环；
    如果写成 async def 却在里面调同步数据库，一个慢请求就能把整个服务拖住。
    这是阶段 0 选「同步」时就要记住的配套纪律。

    读文件用 `file.file.read()`（底层的同步文件对象）而不是 `await file.read()`，
    也是为了让执行模型保持一致 —— 既然整个函数是同步的，就别混异步调用。
    """
    raw = file.file.read()

    # .bib 文件多数是 utf-8，也可能带 BOM；utf-8-sig 能同时兼容这两种情况。
    # 万一碰到别的编码，兜底用 latin-1 解出来（不会抛错），
    # 总比让整个请求 500 要好 —— 用户至少能看到解析结果的报错。
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    return import_bibtex(db, text)
