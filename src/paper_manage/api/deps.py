"""FastAPI 的共享依赖。

把「要一个数据库 session」「要校验 API Key」这类横切需求抽成依赖，
路由函数只管声明「我需要它」，不关心它怎么来的、怎么实现的。

这也是为什么用 Depends 而不是写中间件：
  1. 中间件不知道某个路由到底需不需要鉴权，只能一刀切；
  2. 依赖会体现在 OpenAPI 里（/docs 上出现 Authorize 按钮），中间件不会；
  3. 测试时可以用 app.dependency_overrides 精确替换掉某一条，中间件很难替换。
"""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from paper_manage.core.security import is_valid_api_key
from paper_manage.db.session import get_db

# 用 Annotated 而不是 `db: Session = Depends(get_db)` 的默认值写法：
#   1. 依赖写在类型注解里、不在默认值里，ruff 的 B008 规则不会被触发；
#   2. 类型检查器能看懂 db 就是 Session。
SessionDep = Annotated[Session, Depends(get_db)]

# auto_error=False：让 FastAPI 不要自己抛错。
# 它的默认行为是「缺 header 就返回 403」，但按 HTTP 语义，
# 「没提供凭据」应该是 401（未认证），403 是「已认证但没权限」。
# 所以我们拿原始值自己判断，才能给出正确的状态码。
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

ApiKeyDep = Annotated[str | None, Depends(_api_key_header)]


def require_api_key(api_key: ApiKeyDep) -> None:
    """写操作的守门人。校验失败抛 401。

    返回 None 是因为这个依赖「只校验、不产出数据」。
    以后如果需要知道「是谁在调」，就让它返回一个用户对象，
    路由里写 `user: CurrentUserDep` 就能拿到。
    """
    if not is_valid_api_key(api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少或无效的 X-API-Key",
            headers={"WWW-Authenticate": "X-API-Key"},
        )
