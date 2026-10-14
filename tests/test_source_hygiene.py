"""源码卫生检查：不让不可见字符和转义残渣溜进代码库。

这个测试是从 scripts/check_source.py 搬过来的 —— 从「手动跑一次的脚本」
升级成「每次跑测试都自动检查」。阶段 7 接上 CI 之后，
这类「语法完全合法、ruff 也不报、只有行为诡异」的问题就再也进不了主干了。

背景：这个项目的 scripts/stage1_check.py 和 scripts/seed_fake_data.py
都曾被 `if __name__ == "__&#8203;main__":` 咬过（复制粘贴时混进 HTML 实体），
表现是脚本静默什么都不做、退出码 0、零报错。
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("src", "scripts", "tests")

SUSPECT_CHARS = {
    "\u200b": "ZERO WIDTH SPACE",
    "\u200c": "ZERO WIDTH NON-JOINER",
    "\u200d": "ZERO WIDTH JOINER",
    "\u2060": "WORD JOINER",
    "\ufeff": "BOM",
    "\u00a0": "NO-BREAK SPACE",
}
SUSPECT_PATTERNS = ("&#", "&nbsp;", "&amp;", "&lt;", "&gt;")

# 检查工具自己的源码里必然写着这些样本字符串，否则它没法描述要查什么。
# 这类「工具把自己也扫进去」的自指问题，写检查类工具时几乎一定会遇到。
SKIP_FILES = {"check_source.py", "test_source_hygiene.py"}


def _python_files() -> list[Path]:
    files: list[Path] = []
    for dirname in SCAN_DIRS:
        target = PROJECT_ROOT / dirname
        if target.exists():
            files.extend(
                path for path in sorted(target.rglob("*.py")) if "__pycache__" not in path.parts
            )
    return files


def test_source_tree_has_no_invisible_characters() -> None:
    problems: list[str] = []
    for path in _python_files():
        if path.name in SKIP_FILES:
            continue
        relative = path.relative_to(PROJECT_ROOT)
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for char, name in SUSPECT_CHARS.items():
                if char in line:
                    problems.append(f"{relative}:{lineno} 含不可见字符 {name}")
            for pattern in SUSPECT_PATTERNS:
                if pattern in line:
                    problems.append(f"{relative}:{lineno} 含转义残留 {pattern!r}")

    assert problems == [], "源码里发现可疑字符：\n" + "\n".join(problems)


def test_scanner_actually_covers_files() -> None:
    """防止扫描范围被改坏、导致这个检查变成「永远通过」。

    一个什么都不扫的检查器是最危险的：它永远绿，却给你虚假的安全感。
    所以给检查器本身也加一条断言。
    """
    assert len(_python_files()) >= 10
