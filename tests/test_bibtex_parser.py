"""BibTeX 解析器的单元测试。

解析器是纯函数（字符串进、数据结构出），所以这些测试不需要数据库、
也不需要起 HTTP —— 这正是「把解析逻辑放在 core 层、不 import fastapi」的回报。
"""

import pytest

from paper_manage.core.bibtex import clean_value, parse, parse_year, split_authors, split_keywords


class TestBasicParsing:
    def test_single_article(self) -> None:
        result = parse("@article{key1, title = {Hello}, year = {2023}}")
        assert len(result.entries) == 1
        entry = result.entries[0]
        assert entry.entry_type == "article"
        assert entry.key == "key1"
        assert entry.fields["title"] == "Hello"
        assert entry.fields["year"] == "2023"

    def test_parenthesis_form(self) -> None:
        result = parse("@article(key1, title = {Hello})")
        assert result.entries[0].fields["title"] == "Hello"

    def test_quoted_value(self) -> None:
        result = parse('@article{k, title = "Hello world"}')
        assert result.entries[0].fields["title"] == "Hello world"

    def test_bare_value(self) -> None:
        result = parse("@article{k, year = 2023}")
        assert result.entries[0].fields["year"] == "2023"

    def test_nested_braces_are_balanced(self) -> None:
        """标题里的 {DNA} 这类保护性花括号不能把值读断。"""
        result = parse("@article{k, title = {The {DNA} of {ice}}}")
        assert result.entries[0].fields["title"] == "The {DNA} of {ice}"

    def test_multiple_entries(self) -> None:
        result = parse("@article{a, title={A}}\n@misc{b, title={B}}")
        assert [e.key for e in result.entries] == ["a", "b"]

    def test_entry_without_fields(self) -> None:
        result = parse("@misc{k}")
        assert result.entries[0].fields == {}

    def test_trailing_comma_is_tolerated(self) -> None:
        result = parse("@article{k, title={T},}")
        assert result.entries[0].fields == {"title": "T"}


class TestSkippedBlocks:
    @pytest.mark.parametrize("kind", ["string", "preamble", "comment"])
    def test_non_entry_blocks_are_skipped(self, kind: str) -> None:
        text = f'@{kind}{{whatever = "x"}}\n@article{{k, title={{T}}}}'
        result = parse(text)
        assert [e.key for e in result.entries] == ["k"]
        assert result.errors == []

    def test_percent_comment_is_ignored(self) -> None:
        """真实 .bib 的注释里经常引用 @key，不能被当成条目开头。

        这一条是回归测试：开发时正是样例文件注释里的 @ 让解析器报了假错误。
        """
        text = "% see @smith2020 for details\n@article{k, title={T}}"
        result = parse(text)
        assert [e.key for e in result.entries] == ["k"]
        assert result.errors == []


class TestErrors:
    def test_missing_equals_reports_error(self) -> None:
        result = parse("@article{k,\n  title {oops},\n  year = {2020}\n}")
        assert result.entries == []
        assert len(result.errors) == 1
        assert "缺少 =" in result.errors[0]
        # 报的是「条目起始行」，不是出错字段所在行 —— 这是有意的：
        # 在大文件里，定位到哪个条目比定位到哪一行更实用。
        assert "第 1 行" in result.errors[0]

    def test_unclosed_brace_reports_error(self) -> None:
        result = parse("@article{k, title = {never closed")
        assert result.entries == []
        assert "没有闭合" in result.errors[0]

    def test_at_without_type_reports_error(self) -> None:
        result = parse("@ {oops}")
        assert result.errors
        assert "没有条目类型" in result.errors[0]

    def test_bad_entry_does_not_kill_later_entries(self) -> None:
        """这就是「部分失败」的设计目标：一条坏了，后面的还得能解析出来。"""
        text = "@article{good1, title={A}}\n@article{bad, title {oops}}\n@article{good2, title={B}}"
        result = parse(text)
        assert [e.key for e in result.entries] == ["good1", "good2"]
        assert len(result.errors) == 1


class TestValueHelpers:
    def test_clean_value_strips_braces(self) -> None:
        assert clean_value("{The {DNA} of ice}") == "The DNA of ice"

    def test_clean_value_collapses_whitespace(self) -> None:
        assert clean_value("line one\n      line two") == "line one line two"

    def test_split_authors_on_and(self) -> None:
        assert split_authors("A One and B Two and C Three") == ["A One", "B Two", "C Three"]

    def test_split_authors_last_first_form(self) -> None:
        assert split_authors("Paxman, Guy J. G.") == ["Guy J. G. Paxman"]

    def test_split_authors_ignores_and_inside_name(self) -> None:
        """`and` 必须被空白包围才算分隔符，否则 Anderson 会被切开。"""
        assert split_authors("Anderson Smith") == ["Anderson Smith"]

    def test_split_keywords_comma_and_semicolon(self) -> None:
        assert split_keywords("a, b; c") == ["a", "b", "c"]

    def test_split_keywords_none(self) -> None:
        assert split_keywords(None) == []

    @pytest.mark.parametrize("raw", ["2023", "{2023}", "in press (2023)"])
    def test_parse_year(self, raw: str) -> None:
        assert parse_year(raw) == 2023

    def test_parse_year_none_when_absent(self) -> None:
        assert parse_year("no year here") is None

    def test_parse_year_none_input(self) -> None:
        assert parse_year(None) is None


class TestMalformedInputPaths:
    """这些用例专门覆盖「只有畸形输入才会走到」的分支。

    覆盖率往往就低在这些地方。它们平时不跑，但真正遇到坏文件时，
    正是它们在决定用户看到的报错是不是能看懂 —— 所以值得专门测。
    """

    def test_quoted_value_with_escaped_quote(self) -> None:
        result = parse(r'@article{k, title = "A \"quoted\" word"}')
        assert result.entries[0].fields["title"] == r"A \"quoted\" word"

    def test_unclosed_quote_reports_error(self) -> None:
        result = parse('@article{k, title = "never closed')
        assert result.entries == []
        assert "引号没有闭合" in result.errors[0]

    def test_missing_value_reports_error(self) -> None:
        result = parse("@article{k, title =")
        assert result.entries == []
        assert "字段值缺失" in result.errors[0]

    def test_entry_type_not_followed_by_brace(self) -> None:
        result = parse('@article "this is not a field list"')
        assert result.entries == []
        assert "应该跟" in result.errors[0]

    def test_unclosed_skip_block_reports_error(self) -> None:
        result = parse("@string{never closed")
        assert result.entries == []
        assert "没有闭合" in result.errors[0]

    def test_key_reaching_end_of_input(self) -> None:
        result = parse("@article{k")
        assert result.entries == []
        assert "引用键后面应该是逗号" in result.errors[0]

    def test_field_list_never_closed(self) -> None:
        result = parse("@article{k,")
        assert result.entries == []
        assert "没有闭合" in result.errors[0]

    def test_unrecognizable_field_name(self) -> None:
        result = parse("@article{k, = {value}}")
        assert result.entries == []
        assert "无法识别的字段名" in result.errors[0]
