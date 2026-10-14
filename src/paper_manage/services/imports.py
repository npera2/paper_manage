"""BibTeX 导入的业务编排。

为什么单独开一个 services 层：
  解析（core/bibtex）是纯文本处理，写库（crud）是纯数据访问，
  而「解析 → 校验 → 去重 → 逐条写库 → 汇总报告」这个流程
  既不属于 HTTP，也不属于任何单一的数据操作。
  它需要一个自己的位置 —— 这就是 service 层的由来。
"""

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from paper_manage import crud
from paper_manage.core.bibtex import (
    BibEntry,
    clean_value,
    parse,
    parse_year,
    split_authors,
    split_keywords,
)
from paper_manage.models import Paper
from paper_manage.schemas import ImportIssue, ImportStats, PaperCreate


def import_bibtex(db: Session, text: str) -> ImportStats:
    """导入 BibTeX 文本，返回统计结果。

    整体策略是「部分成功」：一条坏了不影响其他条，
    坏的记录进 issues，用户拿去改源文件即可。
    这比「要么全成功要么全回滚」更符合批量导入的真实使用场景 ——
    用户不会因为文件里有一条 typo 就丢掉另外 499 条。
    """
    parsed = parse(text)

    # 解析阶段就坏掉的（括号没闭合、缺少等号之类），没有条目序号可给
    issues: list[ImportIssue] = [ImportIssue(reason=err) for err in parsed.errors]
    failed = 0

    # --- 第一步：把每条 BibTeX 记录转成 PaperCreate ---
    # 走 PaperCreate 而不是直接拼 Paper 对象，是为了复用同一套校验规则：
    # 年份范围、DOI 归一化、标签去重、标题不能为空……全都自动生效。
    # 好处是「导入」和「手动创建」对数据的要求必然一致，
    # 不存在「同一个数据走两条路结果不同」这种最难查的 bug。
    prepared: list[tuple[int, str, PaperCreate]] = []
    for index, entry in enumerate(parsed.entries, start=1):
        try:
            prepared.append((index, entry.key, _entry_to_payload(entry)))
        except ValidationError as exc:
            failed += 1
            issues.append(ImportIssue(index=index, key=entry.key, reason=_format_error(exc)))

    # --- 第二步：一次性把库里已有的指纹捞出来 ---
    existing_dois, existing_titles = _load_fingerprints(db, prepared)

    # --- 第三步：逐条去重 + 写入 ---
    created = 0
    skipped = 0
    seen_dois: set[str] = set()
    seen_titles: set[tuple[str, int | None]] = set()

    for index, key, payload in prepared:
        # 去重要同时看两个地方：库里已有的，以及同一个文件里前面出现过的。
        # 只看库不看文件的话，同一份 .bib 里重复的条目会被插两次。
        if payload.doi:
            duplicate = payload.doi in existing_dois or payload.doi in seen_dois
            seen_dois.add(payload.doi)
        else:
            fingerprint = _fingerprint(payload)
            duplicate = fingerprint in existing_titles or fingerprint in seen_titles
            seen_titles.add(fingerprint)

        if duplicate:
            skipped += 1
            continue

        try:
            crud.create_paper(db, payload)
        except IntegrityError as exc:
            # 复合主键冲突、唯一约束冲突都是这条路径。
            # 必须先 rollback：session 出错后处于不可用状态，
            # 不回滚的话后面每一条都会连着失败。
            db.rollback()
            failed += 1
            issues.append(ImportIssue(index=index, key=key, reason=f"写入冲突：{exc.orig}"))
        except SQLAlchemyError as exc:
            db.rollback()
            failed += 1
            issues.append(ImportIssue(index=index, key=key, reason=f"写入失败：{exc}"))
        else:
            created += 1

    # 不变式：total == created + skipped + failed
    # 每条解析出来的条目必然落到三个桶之一，所以这个等式一定成立。
    # 如果哪天它不成立了，说明上面的分支逻辑漏了情况。
    return ImportStats(
        total=len(parsed.entries),
        created=created,
        skipped=skipped,
        failed=failed,
        issues=issues,
    )


def _fingerprint(payload: PaperCreate) -> tuple[str, int | None]:
    """没有 DOI 时的后备去重指纹：标题 + 年份。"""
    return (payload.title, payload.year)


def _load_fingerprints(
    db: Session,
    prepared: list[tuple[int, str, PaperCreate]],
) -> tuple[set[str], set[tuple[str, int | None]]]:
    """一次查库，把已存在的 DOI 和 (标题, 年份) 都捞出来。

    为什么要「一次查完」而不是每条记录查一次：
    导入 500 条就是 500 次数据库往返，网络和查询解析的开销会占掉绝大部分时间。
    合并成一次 IN 查询是 O(1) 次往返 —— 这类「把 N 次查询合并成 1 次」的思路
    在批量接口里到处都是，也是面试常问的优化点。
    """
    dois = [payload.doi for _, _, payload in prepared if payload.doi]
    existing_dois: set[str] = set()
    if dois:
        existing_dois = {
            doi for doi in db.scalars(select(Paper.doi).where(Paper.doi.in_(dois))).all() if doi
        }

    titles = [payload.title for _, _, payload in prepared if not payload.doi]
    existing_titles: set[tuple[str, int | None]] = set()
    if titles:
        rows = db.execute(select(Paper.title, Paper.year).where(Paper.title.in_(titles))).all()
        existing_titles = {(title, year) for title, year in rows}

    return existing_dois, existing_titles


def _entry_to_payload(entry: BibEntry) -> PaperCreate:
    """把一条 BibEntry 映射成 PaperCreate。

    字段映射不是随便拍的，是照 BibTeX 的惯例：
      - article 的发表处叫 journal，inproceedings 的叫 booktitle，
        两个都是「发表在哪」，所以合成一个 venue
      - keywords 正好对得上我们的标签系统，直接用
    """
    fields = entry.fields

    venue = None
    for field_name in ("journal", "booktitle", "publisher", "school"):
        if fields.get(field_name):
            venue = clean_value(fields[field_name])
            break

    # 有些 @misc / @online 条目本来就没有 title。
    # 用引用键兜底，总比因为「标题为空」被整条丢掉要好。
    title = clean_value(fields.get("title", "")) or entry.key

    return PaperCreate.model_validate(
        {
            "title": title,
            "abstract": clean_value(fields["abstract"]) if fields.get("abstract") else None,
            "year": parse_year(fields.get("year")),
            "venue": venue,
            "doi": clean_value(fields["doi"]) if fields.get("doi") else None,
            "authors": [{"name": name} for name in split_authors(fields.get("author", ""))],
            "tags": split_keywords(fields.get("keywords")),
        }
    )


def _format_error(exc: ValidationError) -> str:
    """把 Pydantic 的报错压成一行人能读的话。"""
    parts = []
    for err in exc.errors():
        location = ".".join(str(part) for part in err["loc"])
        parts.append(f"{location}: {err.get('msg', '')}")
    return "; ".join(parts)
