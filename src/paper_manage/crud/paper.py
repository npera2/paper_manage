"""论文的数据访问层。

这一层只跟数据库打交道，完全不碰 HTTP。
好处：将来写测试可以直接调这些函数，不用起 HTTP 服务。
"""

from sqlalchemy import func, insert, nulls_last, or_, select
from sqlalchemy.orm import Session, selectinload

from paper_manage.models import Author, Paper, Tag, paper_authors
from paper_manage.schemas import AuthorCreate, PaperCreate, PaperUpdate

# 统一的加载选项，防止 N+1。
# 不做这个的话：查 20 篇论文，访问每篇的 .authors 都会单独发一条 SQL，
# 一共 1 + 20 + 20 = 41 条查询。selectinload 会把它变成固定 3 条。
_PAPER_LOAD_OPTIONS = (
    selectinload(Paper.authors),
    selectinload(Paper.tags),
)


def _create_authors(db: Session, items: list[AuthorCreate]) -> list[Author]:
    """作者：库里已有的按名字复用，没有的现场新建。

    去重和去空白已经在 schema 层做完了，这里可以无条件信任输入。
    这是上一阶段做的一道重构：清洗逻辑从 crud 层上移到 schema 边界。
    """
    if not items:
        return []

    names = [item.name for item in items]
    existing = db.scalars(select(Author).where(Author.name.in_(names))).all()
    by_name = {author.name: author for author in existing}

    result: list[Author] = []
    for item in items:
        author = by_name.get(item.name)
        if author is None:
            author = Author(name=item.name, affiliation=item.affiliation)
            db.add(author)
            by_name[item.name] = author
        result.append(author)
    return result


def _resolve_tags(db: Session, names: list[str]) -> list[Tag]:
    """标签：库里已有的直接复用，没有的现场新建。

    同样，名字的去重和清洗已在 schema 层完成。
    """
    if not names:
        return []

    existing = db.scalars(select(Tag).where(Tag.name.in_(names))).all()
    by_name = {tag.name: tag for tag in existing}

    result: list[Tag] = []
    for name in names:
        tag = by_name.get(name)
        if tag is None:
            tag = Tag(name=name)
            db.add(tag)
            by_name[name] = tag
        result.append(tag)
    return result


def _link_authors(db: Session, paper: Paper, authors: list[Author]) -> None:
    """给论文挂作者，并把署名顺序写进关联表。

    为什么不用 `paper.authors = authors`：
    relationship 自动插关联行时只填两个外键，author_order 只能拿到
    数据库的默认值 0。而署名顺序（一作 / 通讯）在学术里是有意义的，
    所以这里手工插关联表，把顺序一起写进去。

    这是 ORM 抽象「不够用」时该有的判断：能用高层 API 就用；一旦需要
    控制中间表的额外列，退回手写语句是正常做法，不是 hack。
    """
    if not authors:
        return

    # 新论文和新作者此刻还只是内存对象，要先 flush 拿到主键才能建关联
    db.flush()
    db.execute(
        insert(paper_authors),
        [
            {"paper_id": paper.id, "author_id": author.id, "author_order": order}
            for order, author in enumerate(authors)
        ],
    )


def create_paper(db: Session, payload: PaperCreate) -> Paper:
    """新建一篇论文，并处理作者/标签关联。"""
    paper = Paper(
        title=payload.title,
        abstract=payload.abstract,
        year=payload.year,
        venue=payload.venue,
        doi=payload.doi,
    )
    db.add(paper)

    authors = _create_authors(db, payload.authors)
    tags = _resolve_tags(db, payload.tags)

    # 作者必须走手工插关联表（要写 author_order）；
    # 标签的关联表没有额外列，用 relationship 最省事，两种做法各有适用场景。
    _link_authors(db, paper, authors)
    paper.tags = tags

    db.commit()
    # expire_on_commit=False，所以 commit 后这些属性还在，不需要 refresh
    return paper


def get_paper(db: Session, paper_id: int) -> Paper | None:
    """按 id 取单篇，并把作者/标签一次性载入。"""
    stmt = select(Paper).options(*_PAPER_LOAD_OPTIONS).where(Paper.id == paper_id)
    return db.scalar(stmt)


def list_papers(
    db: Session,
    *,
    author: str | None = None,
    year: int | None = None,
    tag: str | None = None,
    q: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Paper], int]:
    """组合检索 + 分页。返回 (当页数据, 满足条件的总条数)。"""
    # 先把条件攒成一个列表：count 和取数据用同一份条件，
    # 这样「总数」和「当页数据」的口径必然一致。
    conditions = []

    if author:
        # .any() 生成 EXISTS 子查询：只要这篇论文的任一作者名字匹配就算命中
        conditions.append(Paper.authors.any(Author.name.ilike(f"%{author}%")))
    if tag:
        # 标签是受控词表，用精确匹配（也只有精确匹配才走得了索引）
        conditions.append(Paper.tags.any(Tag.name == tag))
    if year is not None:
        conditions.append(Paper.year == year)
    if q:
        pattern = f"%{q}%"
        conditions.append(or_(Paper.title.ilike(pattern), Paper.abstract.ilike(pattern)))

    total = db.scalar(select(func.count()).select_from(Paper).where(*conditions)) or 0

    stmt = (
        select(Paper)
        .where(*conditions)
        .options(*_PAPER_LOAD_OPTIONS)
        # 排序键必须能唯一确定顺序。只按 year 排的话，同年份那批论文之间
        # 的先后是数据库"随便"给的，翻页时会出现重复或漏行。
        # 把唯一的 id 放最后当"决胜键"就解决了。nulls_last 让没年份的排在最后。
        .order_by(nulls_last(Paper.year.desc()), Paper.id.desc())
        .limit(limit)
        .offset(offset)
    )
    items = list(db.scalars(stmt).all())
    return items, total


def update_paper(db: Session, paper: Paper, payload: PaperUpdate) -> Paper:
    """局部更新：只改请求里真正出现过的字段。"""
    # exclude_unset=True 只取出「请求体里出现过的键」。
    # 这样 PATCH {"year": 2024} 不会顺手把 title 清成 None。
    data = payload.model_dump(exclude_unset=True)

    # tags 要特殊处理：传进来的是名字列表，得换成 Tag 对象
    tag_names = data.pop("tags", None)
    if tag_names is not None:
        paper.tags = _resolve_tags(db, tag_names)

    for field, value in data.items():
        setattr(paper, field, value)

    db.commit()
    return paper


def delete_paper(db: Session, paper: Paper) -> None:
    """删除论文。关联表里的行由数据库的 ON DELETE CASCADE 自动清掉。"""
    db.delete(paper)
    db.commit()
