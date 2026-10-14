"""鉴权相关测试。

这一组同时演示了「依赖注入」最大的回报：测试可以直接把 require_api_key 换掉，
不用去构造真实密钥、也不用改一行业务代码。
"""

from typing import Any

from fastapi.testclient import TestClient

from paper_manage.api.deps import require_api_key
from paper_manage.main import app


class TestWriteOperationsRequireKey:
    def test_create_without_key_returns_401(
        self, client: TestClient, paper_payload: dict[str, Any]
    ) -> None:
        assert client.post("/papers", json=paper_payload).status_code == 401

    def test_create_with_wrong_key_returns_401(
        self, client: TestClient, paper_payload: dict[str, Any]
    ) -> None:
        response = client.post(
            "/papers",
            json=paper_payload,
            headers={"X-API-Key": "definitely-not-the-key"},
        )
        assert response.status_code == 401

    def test_create_with_correct_key_returns_201(
        self, client: TestClient, auth_headers: dict[str, str], paper_payload: dict[str, Any]
    ) -> None:
        assert client.post("/papers", json=paper_payload, headers=auth_headers).status_code == 201

    def test_patch_requires_key(self, client: TestClient, create_paper: Any) -> None:
        paper = create_paper()
        response = client.patch(f"/papers/{paper['id']}", json={"year": 2000})
        assert response.status_code == 401

    def test_delete_requires_key(self, client: TestClient, create_paper: Any) -> None:
        paper = create_paper()
        assert client.delete(f"/papers/{paper['id']}").status_code == 401

    def test_import_requires_key(self, client: TestClient) -> None:
        response = client.post("/papers/import", json={"bibtex": "@misc{k, title={T}}"})
        assert response.status_code == 401

    def test_upload_requires_key(self, client: TestClient) -> None:
        response = client.post(
            "/papers/import/upload",
            files={"file": ("s.bib", b"@misc{k, title={T}}", "text/plain")},
        )
        assert response.status_code == 401


class TestReadOperationsArePublic:
    def test_list_without_key(self, client: TestClient) -> None:
        assert client.get("/papers").status_code == 200

    def test_detail_without_key(self, client: TestClient, create_paper: Any) -> None:
        paper = create_paper()
        assert client.get(f"/papers/{paper['id']}").status_code == 200


class TestErrorEnvelope:
    def test_401_uses_unified_error_shape(
        self, client: TestClient, paper_payload: dict[str, Any]
    ) -> None:
        body = client.post("/papers", json=paper_payload).json()
        # 统一成 {"error": {...}}：前端不用为「校验失败」和「HTTP 异常」写两套解析
        assert body["error"]["code"] == "http_error"
        assert "X-API-Key" in body["error"]["message"]

    def test_401_carries_www_authenticate_header(
        self, client: TestClient, paper_payload: dict[str, Any]
    ) -> None:
        response = client.post("/papers", json=paper_payload)
        assert response.headers["WWW-Authenticate"] == "X-API-Key"


class TestDependencyOverride:
    """演示依赖注入的真正回报：测试可以把依赖换掉，业务代码一行不改。"""

    def test_override_disables_auth(
        self, client: TestClient, paper_payload: dict[str, Any]
    ) -> None:
        # 先确认正常情况：没有 key 进不去
        assert client.post("/papers", json=paper_payload).status_code == 401

        app.dependency_overrides[require_api_key] = lambda: None
        try:
            assert client.post("/papers", json=paper_payload).status_code == 201
        finally:
            # 必须清掉，否则会污染后面的测试。
            # 这里只弹出我们自己加的这一条（client fixture 里还有 get_db 的覆盖，
            # 用 clear() 会把它一起清掉）。
            app.dependency_overrides.pop(require_api_key, None)
