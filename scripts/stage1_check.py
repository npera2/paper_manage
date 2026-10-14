"""阶段 1 手工验证脚本：建表 -> 写入 -> 关闭 session -> 新 session 读回。

临时脚本，阶段 5 写完正式测试后删掉。
注意：每次运行都会 drop 全库重建，只对开发库用。
"""

from sqlalchemy import select

from paper_manage.db.base import Base
from paper_manage.db.session import SessionLocal, engine
from paper_manage.models import Author, Paper, Tag


def reset_schema() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    print("建表完成，当前注册的表：")
    for name in sorted(Base.metadata.tables):
        print("  -", name)


def seed() -> int:
    with SessionLocal() as session:
        author_a = Author(name="Alice Zhang", affiliation="Polar Research Institute")
        author_b = Author(name="Bob Li", affiliation="Ocean University")
        tag_a = Tag(name="glaciology")
        tag_b = Tag(name="remote-sensing")

        paper = Paper(
            title="Automatic extraction of subglacial valleys from radar data",
            abstract="We present a method for mapping subglacial valleys.",
            year=2023,
            venue="Journal of Glaciology",
            doi="10.1000/example.2023.001",
        )
        paper.authors = [author_a, author_b]
        paper.tags = [tag_a, tag_b]

        session.add(paper)
        session.commit()

        new_id = paper.id
        print("写入完成, paper.id =", new_id)
        return new_id


def read_back(paper_id: int) -> None:
    with SessionLocal() as session:
        paper = session.scalar(select(Paper).where(Paper.id == paper_id))
        if paper is None:
            print("没查到！")
            return

        print("读回标题 :", paper.title)
        print("读回年份 :", paper.year)
        print("读回 DOI :", paper.doi)
        print("作者     :", [a.name for a in paper.authors])
        print("标签     :", [t.name for t in paper.tags])

        found = session.scalars(select(Paper).where(Paper.year == 2023)).all()
        print("按年份 2023 检索 ->", len(found), "篇")


if __name__ == "__main__":
    reset_schema()
    paper_id = seed()
    read_back(paper_id)
