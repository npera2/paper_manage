"""FastAPI 的共享依赖。

把「要一个数据库 session」这种横切需求抽成依赖，
路由函数只管声明「我需要它」，不关心它怎么来的。
阶段 3 的鉴权也放这里，和 get_db 组成依赖链。
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from paper_manage.db.session import get_db

# 用 Annotated 而不是 `db: Session = Depends(get_db)` 的默认值写法：
#   1. 依赖写在类型注解里、不在默认值里，ruff 的 B008 规则不会被触发；
#   2. 类型检查器能看懂 db 就是 Session。
# 路由里只要写 `db: SessionDep`，不用到处重复 Depends(get_db)。
SessionDep = Annotated[Session, Depends(get_db)]
