"""源码卫生扫描：揪出肉眼看不见、但会让代码行为诡异的字符。

为什么需要它：
  2026-10-14 这个项目被同一个问题咬了两次 ——
  从聊天窗口复制代码时，`"__main__"` 变成了 `"__&#8203;main__"`
  （`&#8203;` 是 HTML 转义后的零宽空格，成了 8 个可见的 ASCII 字符）。
  这种写法**语法完全合法、ruff 也不报**，唯一的表现是「脚本默默什么都不做」，
  极难排查。所以专门写个扫描器，主动把它揪出来。

用法：
    uv run python scripts/check_source.py

退出码：发现可疑字符返回 1，干净返回 0。
这样它以后可以直接挂进 CI（阶段 7），让这类问题永远进不了主干。
"""

import sys
from pathlib import Path

# 不可见 / 容易被转义链路篡改的字符
SUSPECT_CHARS = {
    "\u200b": "ZERO WIDTH SPACE",
    "\u200c": "ZERO WIDTH NON-JOINER",
    "\u200d": "ZERO WIDTH JOINER",
    "\u2060": "WORD JOINER",
    "\ufeff": "ZERO WIDTH NO-BREAK SPACE / BOM",
    "\u00a0": "NO-BREAK SPACE",
}

# 会被某种转义链路留下的字面量。&# 开头的 HTML 实体在这里基本不可能是本意。
SUSPECT_PATTERNS = ("&#", "&nbsp;", "&amp;", "&lt;", "&gt;")

SCAN_DIRS = ("src", "scripts", "tests")

# 扫描器自己的源码里必然包含这些样本字符串，否则它就没法描述要查什么。
# 所以显式跳过它自己 —— 这类「工具把自己也扫进去」的自指问题，
# 写检查类工具时几乎一定会遇到。
SKIP_FILES = {"check_source.py"}


def scan_file(path: Path) -> list[str]:
    """返回这个文件里的问题列表，每条是「行号 + 说明」。"""
    problems: list[str] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        for char, name in SUSPECT_CHARS.items():
            if char in line:
                problems.append(f"{path}:{lineno}  不可见字符 {name} (U+{ord(char):04X})")
        for pattern in SUSPECT_PATTERNS:
            if pattern in line:
                problems.append(f"{path}:{lineno}  疑似转义残留 {pattern!r}：{line.strip()[:60]}")
    return problems


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    all_problems: list[str] = []
    scanned = 0

    for dirname in SCAN_DIRS:
        target = root / dirname
        if not target.exists():
            continue
        for path in sorted(target.rglob("*.py")):
            if "__pycache__" in path.parts or path.name in SKIP_FILES:
                continue
            scanned += 1
            all_problems.extend(scan_file(path))

    if all_problems:
        print(f"扫了 {scanned} 个文件，发现 {len(all_problems)} 处问题：")
        for problem in all_problems:
            print("  " + problem)
        return 1

    print(f"扫了 {scanned} 个文件，干净 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
