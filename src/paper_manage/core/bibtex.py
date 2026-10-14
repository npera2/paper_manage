"""一个够用的 BibTeX 解析器。

为什么自己写、不直接引 bibtexparser：
  1. 我们只需要「取出条目和字段值」这一个能力，用不上完整语法；
  2. 少一个依赖、少一份升级折腾；
  3. 自己写才能把「部分失败怎么报告」这件事设计清楚。
如果以后要支持 @string 宏展开、LaTeX 转义反解析这些完整语义，
换回 bibtexparser 也来得及 —— 对外接口就是下面这个 parse() 函数。

支持的语法子集：
    @article{key, title = {..}, year = 2023, ...}
    @article(key, ...)                 圆括号形式也认
    值可以是 {花括号}、"双引号"、裸数字或裸词
    @string / @preamble / @comment     整块跳过
    值里的嵌套花括号会被正确平衡（比如标题里的 {DNA}）

暂不支持的（真实世界的 .bib 里偶尔会遇到）：
    # 字符串拼接、宏展开、LaTeX 转义解码（{\\"o} 这类会原样保留）

这一层是纯文本处理，不 import fastapi、不 import 数据库，
所以它能被单元测试直接喂字符串，不需要起服务、不需要连库。
"""

import re
from dataclasses import dataclass, field

# 这些块不是文献条目，整块跳过就行
_SKIP_TYPES = {"string", "preamble", "comment"}

# BibTeX 用 ` and ` 分隔作者，前后必须有空白
_AUTHOR_SEP = re.compile(r"\s+and\s+", re.IGNORECASE)

# 年份兜底：从 "2023"、"{2023}"、"in press (2023)" 里捞一个 4 位数
_YEAR_RE = re.compile(r"\b[12][0-9]{3}\b")

# 标签分隔：逗号或分号都见过
_TAG_SEP = re.compile(r"[;,]")


@dataclass
class BibEntry:
    """一条 BibTeX 记录。"""

    entry_type: str
    key: str
    fields: dict[str, str]
    line: int = 0


@dataclass
class BibParseResult:
    """解析结果。

    entries 和 errors 是两个独立的出口：解析是「尽力而为」的，
    某一条坏了不会中断整份文件，坏的那条进 errors，好的照常进 entries。
    这样用户一次就能看到所有问题，而不是修一个跑一次。
    """

    entries: list[BibEntry] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def clean_value(value: str) -> str:
    """去掉值里的花括号保护层，并把换行/多空格压成单个空格。

    BibTeX 用花括号保护大小写（{DNA}）或包住特殊字符。
    我们要的是给人看的文本，所以剥掉花括号、保留里面的内容。

    压空白是必须的：.bib 里长标题常常跨好几行书写，
    不处理的话数据库里会存进一堆换行和缩进。
    """
    chars = [ch for ch in value if ch not in "{}"]
    return " ".join("".join(chars).split())


def split_authors(raw: str) -> list[str]:
    """按 BibTeX 规则拆作者，并把「姓, 名」转成「名 姓」。

    单个作者支持两种写法：
        "Last, First"   -> "First Last"
        "First Last"    -> 保持原样
    暂不处理 von / Jr. 这些复杂形式 —— 那需要完整实现 BibTeX 的姓名语法，
    对当前需求不值得。
    """
    result: list[str] = []
    for part in _AUTHOR_SEP.split(clean_value(raw)):
        part = part.strip()
        if not part:
            continue
        if "," in part:
            last, _, first = part.partition(",")
            name = f"{first.strip()} {last.strip()}".strip()
        else:
            name = part
        if name:
            result.append(name)
    return result


def split_keywords(raw: str | None) -> list[str]:
    """把 keywords 字段拆成标签列表。逗号和分号都当分隔符。"""
    if not raw:
        return []
    return [part.strip() for part in _TAG_SEP.split(clean_value(raw)) if part.strip()]


def parse_year(raw: str | None) -> int | None:
    """从年份字段里抠出 4 位年份。

    BibTeX 的 year 不一定是纯数字：可能是 {2023}、也可能是 "in press"。
    所以用正则捞；捞不到就返回 None，交给 schema 层的范围校验去判断。
    """
    if not raw:
        return None
    match = _YEAR_RE.search(clean_value(raw))
    return int(match.group(0)) if match else None


def _skip_ws(text: str, i: int) -> int:
    """跳过空白字符。"""
    n = len(text)
    while i < n and text[i].isspace():
        i += 1
    return i


def _read_balanced(text: str, i: int, open_ch: str, close_ch: str) -> tuple[str, int]:
    """从 i 处的 open_ch 开始读到配对的 close_ch，返回 (内容, 新位置)。

    只数括号深度就够了，不需要理解里面的内容 —— 这是括号平衡类解析的通用套路。
    """
    depth = 0
    n = len(text)
    start = i + 1
    while i < n:
        if text[i] == open_ch:
            depth += 1
        elif text[i] == close_ch:
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1
        i += 1
    raise ValueError(f"{open_ch} 没有闭合")


def _read_quoted(text: str, i: int) -> tuple[str, int]:
    """读一个 "..." 值。反斜杠转义的下一个字符直接跳过。"""
    n = len(text)
    start = i + 1
    i += 1
    while i < n:
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == '"':
            return text[start:i], i + 1
        i += 1
    raise ValueError("引号没有闭合")


def _read_value(text: str, i: int) -> tuple[str, int]:
    """读一个字段值：{...}、"..."、或者裸数字/裸词。"""
    if i >= len(text):
        raise ValueError("字段值缺失")

    ch = text[i]
    if ch == "{":
        return _read_balanced(text, i, "{", "}")
    if ch == '"':
        return _read_quoted(text, i)

    # 裸值：读到逗号、右括号或换行为止（数字、宏名走这条路）
    start = i
    n = len(text)
    while i < n and text[i] not in ",)}\n\r":
        i += 1
    return text[start:i].strip(), i


def _parse_entry(text: str, i: int) -> tuple[BibEntry | None, int, str | None]:
    """解析一个 @... 条目，返回 (条目, 新位置, 错误消息)。"""
    n = len(text)
    i += 1  # 跳过 @

    # --- 条目类型 ---
    start = i
    while i < n and (text[i].isalnum() or text[i] == "_"):
        i += 1
    entry_type = text[start:i].lower()
    if not entry_type:
        return None, i, "`@` 后面没有条目类型"

    i = _skip_ws(text, i)
    if i >= n or text[i] not in "{(":
        return None, i, f"@{entry_type} 后面应该跟 {{ 或 ("
    open_ch = text[i]
    close_ch = "}" if open_ch == "{" else ")"

    # --- @string / @preamble / @comment 整块跳过 ---
    if entry_type in _SKIP_TYPES:
        try:
            _, i = _read_balanced(text, i, open_ch, close_ch)
        except ValueError as exc:
            return None, n, str(exc)
        return None, i, None

    # --- 引用键 ---
    i += 1
    start = i
    while i < n and text[i] not in ",}":
        i += 1
    key = text[start:i].strip()

    if i < n and text[i] == ",":
        i += 1
    elif i < n and text[i] == close_ch:
        # @misc{key} 这种没有字段的条目
        return BibEntry(entry_type=entry_type, key=key, fields={}), i + 1, None
    else:
        return None, i, f"条目 {key or '(无键)'} 的引用键后面应该是逗号"

    # --- 字段列表 ---
    fields: dict[str, str] = {}
    while True:
        i = _skip_ws(text, i)
        if i >= n:
            return None, i, f"条目 {key} 没有闭合的 {close_ch}"
        if text[i] == close_ch:
            i += 1
            break

        # 字段名
        start = i
        while i < n and (text[i].isalnum() or text[i] in "_-"):
            i += 1
        name = text[start:i].lower()
        if not name:
            return None, i, f"条目 {key} 里有无法识别的字段名"

        # 等号
        i = _skip_ws(text, i)
        if i >= n or text[i] != "=":
            return None, i, f"条目 {key} 的字段 {name} 后面缺少 ="
        i = _skip_ws(text, i + 1)

        # 值
        try:
            value, i = _read_value(text, i)
        except ValueError as exc:
            return None, i, f"条目 {key} 的字段 {name}: {exc}"
        fields[name] = value

        # 字段之间的分隔逗号
        i = _skip_ws(text, i)
        if i < n and text[i] == ",":
            i += 1

    return BibEntry(entry_type=entry_type, key=key, fields=fields), i, None


def parse(text: str) -> BibParseResult:
    """把 BibTeX 文本解析成条目列表。

    条目之外的普通文本（.bib 里常见的手写注释）会被安静地忽略。
    """
    result = BibParseResult()
    n = len(text)
    i = 0
    line = 1

    while i < n:
        if text[i] == "%":
            # BibTeX 注释：从 % 一直到行尾。
            # 必须显式跳过，否则注释里出现的 @ 会被当成条目开头 ——
            # 而真实 .bib 的注释经常写着 "% see @smith2020" 这种引用。
            newline = text.find("\n", i)
            # 只跳到换行符本身、不跳过它，让下面那个分支继续负责行号累加
            i = n if newline == -1 else newline
            continue

        if text[i] != "@":
            line += 1 if text[i] == "\n" else 0
            i += 1
            continue

        start_line = line
        entry, new_i, err = _parse_entry(text, i)

        # 行号用「消耗掉的片段里有几个换行」来累加，
        # 这样整个解析过程是线性的，不会每遇到一个 @ 就从头数一遍。
        line += text.count("\n", i, new_i)
        i = new_i

        if err is not None:
            result.errors.append(f"第 {start_line} 行: {err}")
        elif entry is not None:
            entry.line = start_line
            result.entries.append(entry)

    return result
