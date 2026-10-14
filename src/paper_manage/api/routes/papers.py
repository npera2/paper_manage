"""论文接口。

路由层只做三件事：收参数、调 crud 层、决定返回什么状态码。
业务逻辑一律不写在这里。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status

from paper_manage import crud
from paper_manage.api.deps import SessionDep, require_api_key
from paper_manage.schemas import PaperCreate, PaperPage, PaperRead, PaperUpdate

router = APIRouter(prefix="/papers", tags=["papers"])


@router.post(
    "",
    response_model=PaperRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
)
def create_paper(payload: PaperCreate, db: SessionDep) -> PaperRead:
    """新建一篇论文。"""
    paper = crud.create_paper(db, payload)
    return PaperRead.model_validate(paper)


@router.get("", response_model=PaperPage)
def search_papers(
    db: SessionDep,
    author: Annotated[str | None, Query(description="按作者名模糊匹配")] = None,
    year: Annotated[int | None, Query(ge=1000, le=2100, description="按年份精确匹配")] = None,
    tag: Annotated[str | None, Query(description="按标签名精确匹配")] = None,
    q: Annotated[str | None, Query(description="在标题和摘要里模糊搜索")] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="每页条数")] = 20,
    offset: Annotated[int, Query(ge=0, description="跳过多少条")] = 0,
) -> PaperPage:
    """组合检索：四个筛选条件都可以任意组合，结果按年份倒序分页返回。"""
    items, total = crud.list_papers(
        db, author=author, year=year, tag=tag, q=q, limit=limit, offset=offset
    )
    return PaperPage(
        total=total,
        limit=limit,
        offset=offset,
        items=[PaperRead.model_validate(paper) for paper in items],
    )


@router.get("/{paper_id}", response_model=PaperRead)
def read_paper(
    db: SessionDep,
    paper_id: Annotated[int, Path(ge=1, description="论文 id")],
) -> PaperRead:
    """按 id 取单篇论文。"""
    paper = crud.get_paper(db, paper_id)
    if paper is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="论文不存在")
    return PaperRead.model_validate(paper)


@router.patch(
    "/{paper_id}",
    response_model=PaperRead,
    dependencies=[Depends(require_api_key)],
)
def update_paper(
    db: SessionDep,
    paper_id: Annotated[int, Path(ge=1, description="论文 id")],
    payload: PaperUpdate,
) -> PaperRead:
    """局部更新，只改请求里传了的字段。"""
    paper = crud.get_paper(db, paper_id)
    if paper is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="论文不存在")
    paper = crud.update_paper(db, paper, payload)
    return PaperRead.model_validate(paper)


@router.delete(
    "/{paper_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(require_api_key)],
)
def delete_paper(
    db: SessionDep,
    paper_id: Annotated[int, Path(ge=1, description="论文 id")],
) -> None:
    """删除论文。204 表示成功但没有响应体。"""
    paper = crud.get_paper(db, paper_id)
    if paper is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="论文不存在")
    crud.delete_paper(db, paper)
