"""健康检查与 API 文档。"""

from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_needs_no_api_key(client: TestClient) -> None:
    """健康检查必须公开，否则容器编排里的 healthcheck 会一直失败。"""
    assert client.get("/health").status_code == 200


def test_openapi_schema_is_served(client: TestClient) -> None:
    """OpenAPI 文档能正常生成，顺带确认所有路由都注册上了。"""
    response = client.get("/openapi.json")
    assert response.status_code == 200

    paths = response.json()["paths"]
    assert "/papers" in paths
    assert "/papers/{paper_id}" in paths
    assert "/papers/import" in paths
    assert "/papers/import/upload" in paths


def test_import_routes_are_not_shadowed_by_wildcard(client: TestClient) -> None:
    """路由顺序回归测试。

    /papers/{paper_id} 是通配路径。如果 papers 路由注册在 imports 之前，
    请求 /papers/import 会被它抢走、把 "import" 当 paper_id 解析 → 直接 422。
    这个测试就是钉死「imports 必须排在前面」这条规则。
    """
    response = client.post("/papers/import", json={"bibtex": "@misc{k, title={T}}"})
    # 没有 API Key 应该是 401（鉴权拦住了），而**不是** 422（被当成不合法的 paper_id）
    assert response.status_code == 401
