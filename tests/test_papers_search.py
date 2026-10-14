"""组合检索与分页。

筛选条件的正确性靠「总量 + 命中内容」两条一起断言：
只断言总量，改错了条件可能碰巧数量一样；只断言内容，可能会漏掉多余结果。
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

# 4 篇特征各异的论文：年份有重合、有 None；标签有交集；作者有重合
SAMPLE_PAPERS: list[dict[str, Any]] = [
    {
        "title": "Glacier retreat in Greenland",
        "year": 2020,
        "abstract": "warming effects on ice",
        "tags": ["glaciology"],
        "authors": [{"name": "Alice Zhang"}],
    },
    {
        "title": "Bedrock mapping with radar",
        "year": 2021,
        "abstract": "subglacial survey methods",
        "tags": ["glaciology", "remote-sensing"],
        "authors": [{"name": "Bob Li"}],
    },
    {
        "title": "Ocean circulation model",
        "year": 2020,
        "abstract": "a glacier adjacent study",
        "tags": ["oceanography"],
        "authors": [{"name": "Carol Wang"}],
    },
    {
        "title": "Antarctic ice shelf dynamics",
        "year": None,
        "abstract": "shelf flow",
        "tags": [],
        "authors": [{"name": "Alice Zhang"}],
    },
]


@pytest.fixture
def sample_papers(client: TestClient, auth_headers: dict[str, str]) -> list[dict[str, Any]]:
    """造 4 篇论文，返回按创建顺序排列的响应体。"""
    created = []
    for payload in SAMPLE_PAPERS:
        response = client.post("/papers", json=payload, headers=auth_headers)
        assert response.status_code == 201, response.text
        created.append(response.json())
    return created


class TestFilters:
    def test_no_filter_returns_everything(
        self, client: TestClient, sample_papers: list[dict[str, Any]]
    ) -> None:
        body = client.get("/papers").json()
        assert body["total"] == 4
        assert len(body["items"]) == 4

    def test_filter_by_year(self, client: TestClient, sample_papers: list[dict[str, Any]]) -> None:
        body = client.get("/papers", params={"year": 2020}).json()
        assert body["total"] == 2
        assert {item["title"] for item in body["items"]} == {
            "Glacier retreat in Greenland",
            "Ocean circulation model",
        }

    def test_filter_by_tag_is_exact_match(
        self, client: TestClient, sample_papers: list[dict[str, Any]]
    ) -> None:
        assert client.get("/papers", params={"tag": "glaciology"}).json()["total"] == 2
        # 标签是受控词表，用精确匹配：部分匹配不应该命中
        assert client.get("/papers", params={"tag": "glacio"}).json()["total"] == 0

    def test_filter_by_author_partial_and_case_insensitive(
        self, client: TestClient, sample_papers: list[dict[str, Any]]
    ) -> None:
        body = client.get("/papers", params={"author": "zhang"}).json()
        assert body["total"] == 2

    def test_q_searches_title_and_abstract(
        self, client: TestClient, sample_papers: list[dict[str, Any]]
    ) -> None:
        """glacier 出现在 1 篇的标题里、另 1 篇的摘要里，两边都要命中。"""
        body = client.get("/papers", params={"q": "glacier"}).json()
        assert body["total"] == 2

    def test_combined_filters(
        self, client: TestClient, sample_papers: list[dict[str, Any]]
    ) -> None:
        body = client.get("/papers", params={"year": 2020, "tag": "glaciology"}).json()
        assert body["total"] == 1
        assert body["items"][0]["title"] == "Glacier retreat in Greenland"

    def test_no_match_returns_empty_page(
        self, client: TestClient, sample_papers: list[dict[str, Any]]
    ) -> None:
        body = client.get("/papers", params={"q": "no-such-word-anywhere"}).json()
        assert body["total"] == 0
        assert body["items"] == []


class TestOrdering:
    def test_newest_year_first_and_null_last(
        self, client: TestClient, sample_papers: list[dict[str, Any]]
    ) -> None:
        """排序规则：年份倒序；年份相同的按 id 倒序；没年份的排最后。"""
        body = client.get("/papers").json()
        titles = [item["title"] for item in body["items"]]
        assert titles == [
            "Bedrock mapping with radar",  # 2021
            "Ocean circulation model",  # 2020, id 更大
            "Glacier retreat in Greenland",  # 2020, id 更小
            "Antarctic ice shelf dynamics",  # 年份为 None
        ]


class TestPagination:
    def test_total_counts_all_matches_not_just_the_page(
        self, client: TestClient, sample_papers: list[dict[str, Any]]
    ) -> None:
        """total 是「满足条件的总数」，不是「本页条数」—— 前端靠它算总页数。"""
        body = client.get("/papers", params={"limit": 2, "offset": 0}).json()
        assert body["total"] == 4
        assert len(body["items"]) == 2
        assert body["limit"] == 2
        assert body["offset"] == 0

    def test_pages_do_not_overlap(
        self, client: TestClient, sample_papers: list[dict[str, Any]]
    ) -> None:
        """稳定的排序键才能保证翻页不重不漏。

        只按 year 排序的话，同年份那批的先后由数据库随意决定，
        第 1 页看到的和第 2 页可能重复。把唯一的 id 当决胜键就解决了。
        """
        page1 = client.get("/papers", params={"limit": 2, "offset": 0}).json()
        page2 = client.get("/papers", params={"limit": 2, "offset": 2}).json()

        ids1 = {item["id"] for item in page1["items"]}
        ids2 = {item["id"] for item in page2["items"]}
        assert ids1.isdisjoint(ids2)
        assert len(ids1 | ids2) == 4

    def test_offset_beyond_end_returns_empty(
        self, client: TestClient, sample_papers: list[dict[str, Any]]
    ) -> None:
        body = client.get("/papers", params={"offset": 100}).json()
        assert body["total"] == 4
        assert body["items"] == []

    def test_limit_out_of_range_returns_422(self, client: TestClient) -> None:
        assert client.get("/papers", params={"limit": 0}).status_code == 422
        assert client.get("/papers", params={"limit": 101}).status_code == 422

    def test_negative_offset_returns_422(self, client: TestClient) -> None:
        assert client.get("/papers", params={"offset": -1}).status_code == 422
