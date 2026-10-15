"""鉴权相关的接口。

这里只有一个用途：让客户端**在不产生任何副作用的前提下**验证自己的凭据是否有效。

为什么必须单独开一个：本 API 的设计是「读公开、写需鉴权」，
所以 GET /papers、GET /papers/{id} 这些读接口**既不要求也不校验** API Key ——
拿一个完全错误的 key 去读，照样返回 200。

这意味着**没有任何读接口能用来验证凭据**。而如果让客户端靠「随便发个写请求看看」
来验证，那要么真的创建了数据，要么得指望请求体恰好校验失败，都不可靠。
"""

from typing import Any

from fastapi import APIRouter, Depends

from paper_manage.api.deps import require_api_key

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/check", dependencies=[Depends(require_api_key)])
def check_api_key() -> dict[str, Any]:
    """校验 API Key：有效返回 200，缺失或错误返回 401。

    不修改任何数据，可以随便调。
    """
    return {"status": "ok", "message": "API Key 有效"}
