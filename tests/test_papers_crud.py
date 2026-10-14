"""论文 CRUD 接口：正常路径 + 主要错误路径。

一个接口至少要覆盖三种情况：成功、参数不合法、目标不存在。
只测成功路径的测试，价值不到一半。
"""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from paper_manage.models import Author


class TestCreate:
    def test_creates_paper_with_nested_authors_and_tags(
        self, client: TestClient, auth_headers: dict[str, str], paper_payload: dict[str, Any]
    ) -> None:
        response = client.post("/papers", json=paper_payload, headers=auth_headers)

        assert response.status_code == 201
        body = response.json()
        assert body["id"] > 0
        assert body["title"] == paper_payload["title"]
        assert [a["name"] for a in body["authors"]] == ["Alice Zhang", "Bob Li"]
        assert sorted(t["name"] for t in body["tags"]) == ["glaciology", "valley"]
        # created_at 由数据库的 server_default 填，不是 Python 侧生成的
        assert body["created_at"]

    def test_author_order_is_preserved(
        self, client: TestClient, auth_headers: dict[str, str], paper_payload: dict[str, Any]
    ) -> None:
        """署名顺序是有意义的（一作/通讯），关联表的 author_order 决定它。"""
        payload = {
            **paper_payload,
            "authors": [{"name": "First Author"}, {"name": "Second Author"}, {"name": "Third"}],
        }
        body = client.post("/papers", json=payload, headers=auth_headers).json()
        assert [a["name"] for a in body["authors"]] == ["First Author", "Second Author", "Third"]

    def test_duplicate_author_names_are_collapsed(
        self, client: TestClient, auth_headers: dict[str, str], paper_payload: dict[str, Any]
    ) -> None:
        """同一位作者重复出现会被去重。

        不去重的话会插出两条相同的 (paper_id, author_id) 关联行，
        直接撞复合主键报 IntegrityError。
        """
        payload = {
            **paper_payload,
            "authors": [{"name": "Same Person"}, {"name": " Same Person "}],
        }
        body = client.post("/papers", json=payload, headers=auth_headers).json()
        assert [a["name"] for a in body["authors"]] == ["Same Person"]

    def test_reuses_existing_author_rows(
        self, client: TestClient, auth_headers: dict[str, str], paper_payload: dict[str, Any]
    ) -> None:
        """同名作者应该复用同一行，而不是每篇论文都新建一个。"""
        first = client.post("/papers", json=paper_payload, headers=auth_headers).json()
        second = client.post(
            "/papers",
            json={**paper_payload, "doi": "10.5194/tc-2024-002"},
            headers=auth_headers,
        ).json()

        assert {a["id"] for a in first["authors"]} == {a["id"] for a in second["authors"]}

    def test_reuses_existing_tag_rows(
        self, client: TestClient, auth_headers: dict[str, str], paper_payload: dict[str, Any]
    ) -> None:
        first = client.post("/papers", json=paper_payload, headers=auth_headers).json()
        second = client.post(
            "/papers",
            json={**paper_payload, "doi": "10.5194/tc-2024-003"},
            headers=auth_headers,
        ).json()

        assert {t["id"] for t in first["tags"]} == {t["id"] for t in second["tags"]}

    def test_duplicate_doi_returns_409_not_500(
        self, client: TestClient, auth_headers: dict[str, str], paper_payload: dict[str, Any]
    ) -> None:
        """唯一约束冲突要翻译成 409，不能让它变成 500。"""
        client.post("/papers", json=paper_payload, headers=auth_headers)
        response = client.post("/papers", json=paper_payload, headers=auth_headers)

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "conflict"

    def test_rejects_whitespace_only_title(
        self, client: TestClient, auth_headers: dict[str, str], paper_payload: dict[str, Any]
    ) -> None:
        response = client.post(
            "/papers", json={**paper_payload, "title": "   "}, headers=auth_headers
        )
        assert response.status_code == 422
        assert response.json()["error"]["details"][0]["field"] == "title"

    def test_rejects_unknown_field_type(
        self, client: TestClient, auth_headers: dict[str, str], paper_payload: dict[str, Any]
    ) -> None:
        response = client.post(
            "/papers", json={**paper_payload, "year": "not-a-number"}, headers=auth_headers
        )
        assert response.status_code == 422

    def test_rejects_overlong_tag(
        self, client: TestClient, auth_headers: dict[str, str], paper_payload: dict[str, Any]
    ) -> None:
        """标签名超过 64 字符要在边界返回 422，不能拖到数据库层变 500。

        Tag.name 是 String(64)，但 schema 层不挡的话，超长值会一路走到
        数据库才报 DataError —— 那是「服务端错误」的语义，可这明明是客户端传错了。
        """
        response = client.post(
            "/papers",
            json={**paper_payload, "tags": ["x" * 65]},
            headers=auth_headers,
        )
        assert response.status_code == 422


class TestRead:
    def test_get_by_id(self, client: TestClient, create_paper: Any) -> None:
        created = create_paper()
        response = client.get(f"/papers/{created['id']}")

        assert response.status_code == 200
        assert response.json()["id"] == created["id"]

    def test_get_missing_returns_404_with_envelope(self, client: TestClient) -> None:
        response = client.get("/papers/999999")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "http_error"
        assert response.json()["error"]["message"] == "论文不存在"

    def test_zero_id_returns_422(self, client: TestClient) -> None:
        """路径参数有 ge=1 约束，0 应该在进到业务逻辑之前就被挡下。"""
        assert client.get("/papers/0").status_code == 422


class TestUpdate:
    def test_partial_update_changes_only_given_field(
        self, client: TestClient, auth_headers: dict[str, str], create_paper: Any
    ) -> None:
        created = create_paper()
        response = client.patch(
            f"/papers/{created['id']}", json={"year": 1999}, headers=auth_headers
        )

        assert response.status_code == 200
        body = response.json()
        assert body["year"] == 1999
        # PATCH 的关键语义：没传的字段必须原样保留
        assert body["title"] == created["title"]
        assert body["doi"] == created["doi"]
        assert [a["name"] for a in body["authors"]] == ["Alice Zhang", "Bob Li"]

    def test_explicit_null_clears_field(
        self, client: TestClient, auth_headers: dict[str, str], create_paper: Any
    ) -> None:
        """「传了 null」和「没传」必须区别对待，这是 exclude_unset 的功劳。"""
        created = create_paper()
        response = client.patch(
            f"/papers/{created['id']}", json={"venue": None}, headers=auth_headers
        )

        assert response.status_code == 200
        assert response.json()["venue"] is None

    def test_replaces_tags(
        self, client: TestClient, auth_headers: dict[str, str], create_paper: Any
    ) -> None:
        created = create_paper()
        response = client.patch(
            f"/papers/{created['id']}",
            json={"tags": ["new-tag"]},
            headers=auth_headers,
        )

        assert [t["name"] for t in response.json()["tags"]] == ["new-tag"]

    def test_empty_patch_returns_422(
        self, client: TestClient, auth_headers: dict[str, str], create_paper: Any
    ) -> None:
        created = create_paper()
        response = client.patch(f"/papers/{created['id']}", json={}, headers=auth_headers)

        assert response.status_code == 422
        assert "至少要提供一个要修改的字段" in response.text

    def test_patch_missing_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.patch("/papers/999999", json={"year": 2000}, headers=auth_headers)
        assert response.status_code == 404


class TestDelete:
    def test_delete_returns_204_then_get_returns_404(
        self, client: TestClient, auth_headers: dict[str, str], create_paper: Any
    ) -> None:
        created = create_paper()

        response = client.delete(f"/papers/{created['id']}", headers=auth_headers)
        assert response.status_code == 204
        # 204 的语义是「成功但没有响应体」
        assert response.content == b""

        assert client.get(f"/papers/{created['id']}").status_code == 404

    def test_delete_missing_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        assert client.delete("/papers/999999", headers=auth_headers).status_code == 404

    def test_delete_paper_keeps_author_rows(
        self, client: TestClient, auth_headers: dict[str, str], create_paper: Any, db_session: Any
    ) -> None:
        """删论文只清关联表，不该把作者本身删掉。

        作者是独立实体，可能被别的论文引用。
        数据库层的 ON DELETE CASCADE 只作用在 paper_authors 上。
        """
        created = create_paper()
        client.delete(f"/papers/{created['id']}", headers=auth_headers)

        author_count = db_session.scalar(select(func.count()).select_from(Author))
        assert author_count == 2


class TestPatchEdgeCases:
    def test_patch_doi_is_normalized(
        self, client: TestClient, auth_headers: dict[str, str], create_paper: Any
    ) -> None:
        """更新走的必须是同一套归一化规则，不能只在创建时清洗。"""
        created = create_paper()
        response = client.patch(
            f"/papers/{created['id']}",
            json={"doi": "https://doi.org/10.5194/TC-2025-999"},
            headers=auth_headers,
        )

        assert response.json()["doi"] == "10.5194/tc-2025-999"

    def test_patch_tags_to_null_clears_them(
        self, client: TestClient, auth_headers: dict[str, str], create_paper: Any
    ) -> None:
        """「没传 tags」不动标签，「明确传 tags=null」清空标签 —— 两者必须分开。"""
        created = create_paper()
        assert created["tags"]

        response = client.patch(
            f"/papers/{created['id']}", json={"tags": None}, headers=auth_headers
        )

        assert response.json()["tags"] == []
