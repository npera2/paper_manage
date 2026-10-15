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


class TestCredentialCheckEndpoint:
    """/auth/check —— 唯一能用来验证凭据的接口。

    它存在的直接原因是一个真实 bug：控制台的「测试连接」原本调的是 GET /papers，
    而读接口按设计是公开的 —— 于是**随便填什么 key 都显示"连接正常"**，
    用户根本无从知道自己填的 key 对不对。
    """

    def test_rejects_missing_key(self, client: TestClient) -> None:
        assert client.get("/auth/check").status_code == 401

    def test_rejects_wrong_key(self, client: TestClient) -> None:
        response = client.get("/auth/check", headers={"X-API-Key": "definitely-wrong"})
        assert response.status_code == 401

    def test_accepts_correct_key(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        response = client.get("/auth/check", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_has_no_side_effects(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        """「只验凭据」的接口不该改动任何数据 —— 否则客户端就不敢随便调它。"""
        before = client.get("/papers").json()["total"]
        client.get("/auth/check", headers=auth_headers)
        assert client.get("/papers").json()["total"] == before


class TestReadEndpointsDoNotValidateCredentials:
    """回归测试：这就是控制台最初判断错的根源。

    读接口是公开的，拿错误的 key 也能读。所以**没有任何读接口**能用来验证凭据，
    客户端必须调 /auth/check。这条设计如果哪天被改成「读也要鉴权」，
    下面这几个测试会红 —— 那时记得同步改控制台的逻辑。
    """

    def test_list_accepts_any_key(self, client: TestClient) -> None:
        assert client.get("/papers", headers={"X-API-Key": "definitely-wrong"}).status_code == 200

    def test_list_accepts_no_key_at_all(self, client: TestClient) -> None:
        assert client.get("/papers").status_code == 200

    def test_detail_accepts_any_key(self, client: TestClient, create_paper: Any) -> None:
        paper = create_paper()
        headers = {"X-API-Key": "definitely-wrong"}
        assert client.get(f"/papers/{paper['id']}", headers=headers).status_code == 200
