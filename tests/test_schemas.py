"""纯单元测试：不碰数据库、不起 HTTP，只测 Pydantic 校验规则。

这类测试跑得极快（毫秒级），所以应该尽量把「逻辑」下沉到能被这样测的地方。
"""

import pytest
from pydantic import ValidationError

from paper_manage.schemas import PaperCreate, PaperUpdate


class TestDoiNormalization:
    """DOI 归一化：用户从浏览器复制来的带前缀 DOI 要能存干净。"""

    @pytest.mark.parametrize(
        "raw",
        [
            "https://doi.org/10.1000/ABC",
            "http://doi.org/10.1000/ABC",
            "https://dx.doi.org/10.1000/ABC",
            "doi:10.1000/ABC",
            "  10.1000/ABC  ",
        ],
    )
    def test_strips_prefix_and_lowercases(self, raw: str) -> None:
        paper = PaperCreate.model_validate({"title": "t", "doi": raw})
        assert paper.doi == "10.1000/abc"

    def test_none_stays_none(self) -> None:
        paper = PaperCreate.model_validate({"title": "t"})
        assert paper.doi is None


class TestYearValidation:
    def test_rejects_far_future_year(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            PaperCreate.model_validate({"title": "t", "year": 2099})
        # 报错信息要写给人看：assert 的是我们自己的中文提示，而不是 Pydantic 的英文原文
        assert "year 不能晚于" in str(exc_info.value)

    def test_rejects_year_below_range(self) -> None:
        with pytest.raises(ValidationError):
            PaperCreate.model_validate({"title": "t", "year": 999})

    def test_accepts_none(self) -> None:
        assert PaperCreate.model_validate({"title": "t", "year": None}).year is None


class TestTitleValidation:
    def test_rejects_whitespace_only_title(self) -> None:
        """str_strip_whitespace 和 min_length 必须配合，单靠一个挡不住这种输入。"""
        with pytest.raises(ValidationError):
            PaperCreate.model_validate({"title": "   "})

    def test_strips_surrounding_whitespace(self) -> None:
        assert PaperCreate.model_validate({"title": "  hello  "}).title == "hello"


class TestTagCleaning:
    def test_dedupes_and_strips(self) -> None:
        paper = PaperCreate.model_validate({"title": "t", "tags": [" a ", "a", "b", "", "  "]})
        assert paper.tags == ["a", "b"]

    def test_keeps_input_order(self) -> None:
        paper = PaperCreate.model_validate({"title": "t", "tags": ["z", "a", "m"]})
        assert paper.tags == ["z", "a", "m"]


class TestAuthorDeduplication:
    def test_duplicate_authors_are_collapsed(self) -> None:
        """同一篇论文里同一位作者只能出现一次。

        这不只是"干净"的问题：作者关联表是 (paper_id, author_id) 复合主键，
        重复的作者会产生重复的关联行，直接撞主键约束报 IntegrityError。
        """
        paper = PaperCreate.model_validate(
            {
                "title": "t",
                "authors": [{"name": "Alice"}, {"name": " Bob "}, {"name": "Alice"}],
            }
        )
        assert [a.name for a in paper.authors] == ["Alice", "Bob"]


class TestEmptyPatch:
    def test_rejects_empty_body(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            PaperUpdate.model_validate({})
        assert "至少要提供一个要修改的字段" in str(exc_info.value)

    def test_allows_single_field(self) -> None:
        patch = PaperUpdate.model_validate({"year": 2020})
        assert patch.model_dump(exclude_unset=True) == {"year": 2020}

    def test_explicit_null_is_kept_by_exclude_unset(self) -> None:
        """「没传 venue」和「明确传 venue=null」必须能区分开，这是 PATCH 语义的关键。"""
        patch = PaperUpdate.model_validate({"venue": None})
        assert patch.model_dump(exclude_unset=True) == {"venue": None}
