"""阶段 2 用：往库里灌大量假数据，好让 EXPLAIN 能看出索引的作用。

只动 papers / authors / paper_authors 三张表，不碰你阶段 1 那条数据。
重复运行会追加新的一批（doi 带偏移，不会撞唯一约束）。
"""

import random

from sqlalchemy import func, insert, select

from paper_manage.db.session import SessionLocal
from paper_manage.models import Author, Paper, paper_authors

PAPER_COUNT = 20000
AUTHOR_TARGET = 500

VENUES = ["Journal of Glaciology", "The Cryosphere", "Nature Geoscience", "Remote Sensing"]
# 大词表 + 一个只在极少数论文里出现的稀有词，
# 这样才能造出「高选择性查询」来对比走不走索引。
WORDS = [f"term{i:03d}" for i in range(200)]
RARE_WORD = "cryoconite"
RARE_EVERY = 400  # 每 400 篇里有一篇标题含 RARE_WORD


def main() -> None:
    # 固定随机种子：每次生成的数据一样，EXPLAIN 的数字才有可比性
    random.seed(42)

    with SessionLocal() as db:
        # --- 1) 作者：补到 AUTHOR_TARGET 个 ---
        have = db.scalar(select(func.count()).select_from(Author)) or 0
        if have < AUTHOR_TARGET:
            db.execute(
                insert(Author),
                [
                    {"name": f"Author {i:04d}", "affiliation": f"Institute {i % 50:02d}"}
                    for i in range(have, AUTHOR_TARGET)
                ],
            )
            db.commit()
            print(f"作者：新增 {AUTHOR_TARGET - have} 个")

        author_ids = list(db.scalars(select(Author.id)).all())

        # --- 2) 论文：批量插入 ---
        base = db.scalar(select(func.count()).select_from(Paper)) or 0
        rows = []
        for i in range(PAPER_COUNT):
            title = f"{' '.join(random.choices(WORDS, k=8))} no.{base + i}"
            if i % RARE_EVERY == 0:
                title = f"{RARE_WORD} {title}"
            rows.append(
                {
                    "title": title,
                    "abstract": " ".join(random.choices(WORDS, k=30)),
                    "year": random.randint(1950, 2025),
                    "venue": random.choice(VENUES),
                    "doi": f"10.9999/seed.{base + i}",
                }
            )

        # .returning(Paper.id) 让数据库把新插入行的主键回传，
        # 后面建关联时就不用再查一遍（比重新 select 便宜）
        new_ids = [row_id for (row_id,) in db.execute(insert(Paper).returning(Paper.id), rows)]
        db.commit()
        print(f"论文：新增 {len(new_ids)} 篇")

        # --- 3) 关联：只给这次新插入的论文挂 1~3 个作者 ---
        # 注意只处理 new_ids：如果给全表都挂一遍，重复运行会撞复合主键
        links = []
        for paper_id in new_ids:
            for author_id in random.sample(author_ids, k=random.randint(1, 3)):
                links.append({"paper_id": paper_id, "author_id": author_id})
        db.execute(insert(paper_authors), links)
        db.commit()
        print(f"论文-作者关联：新增 {len(links)} 条")


if __name__ == "__&#8203;main__":
    main()
