"""内置 Web 控制台。

它不属于核心业务逻辑，但它是别人第一次接触这个项目时看到的东西 ——
所以至少得保证「打不开」和「调了不存在的接口」这类低级故障能被测出来。
"""

import re

from fastapi.testclient import TestClient


class TestConsoleIsServed:
    def test_root_redirects_to_console(self, client: TestClient) -> None:
        response = client.get("/", follow_redirects=False)
        assert response.status_code in (302, 307)
        assert response.headers["location"] == "/ui/"

    def test_console_page_is_html(self, client: TestClient) -> None:
        response = client.get("/ui/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_console_needs_no_api_key(self, client: TestClient) -> None:
        """控制台本身是公开的 —— 它只是页面，真正要鉴权的是它去调的写接口。"""
        assert client.get("/ui/").status_code == 200


class TestConsoleBackendContract:
    def test_console_only_calls_registered_endpoints(self, client: TestClient) -> None:
        """防「前端调了个不存在的路径」。

        这类问题很阴险：页面加载完全正常、控制台也不报错，
        但一点按钮就 404 —— 而且错误在浏览器里，后端日志干干净净。

        做法：把 HTML 里出现的所有 /papers... 字面量抠出来，
        逐个和 OpenAPI 里注册的路径比对。
        """
        html = client.get("/ui/").text
        registered = set(client.get("/openapi.json").json()["paths"])

        # 匹配静态写的路径字面量。"忽略拼接出来的（"/papers/" + id），
        # 所以 strip 掉末尾斜杠再比。
        referenced = {ref.rstrip("/") for ref in re.findall(r'"(/papers[a-z/]*)"', html)}

        assert referenced, "没在页面里找到任何接口路径，说明正则或页面结构变了"
        for ref in sorted(referenced):
            assert ref in registered, f"控制台调用了未注册的路径：{ref}"

    def test_console_references_the_api_key_header(self, client: TestClient) -> None:
        """写操作必须带鉴权头，否则控制台新建/删除全部会 401。"""
        assert "X-API-Key" in client.get("/ui/").text
