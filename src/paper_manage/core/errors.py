"""统一错误响应格式。

FastAPI 默认的错误体是 {"detail": ...}，而且不同来源的形状不一致：
  - Pydantic 校验失败：{"detail": [ {...}, {...} ]}  ← 一个列表
  - 手动 raise 的 HTTPException：{"detail": "字符串"}
前端得写两套解析逻辑，很难受。

这里把两者都归一成：
    {"error": {"code": "...", "message": "...", "details": [...]}}

注意：错误格式属于「对外契约」，改它会影响到所有调用方。
真实项目里这种改动要写进 CHANGELOG 并提前通知前端。
"""

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException


def register_exception_handlers(app: FastAPI) -> None:
    """把两个全局异常处理器挂到 app 上。"""

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # 只挑出 field 和 message 两个字段，丢掉原始 ctx。
        # 原因：ctx 里可能塞着 ValueError 对象，直接塞进 JSONResponse 会序列化失败。
        details = []
        for err in exc.errors():
            # loc 第一段是来源（body / query / path），从第二段起才是字段路径。
            # 模型级校验（model_validator）没有具体字段，loc 只有第一段，
            # 这时用 body 兜底，前端看到的就不是一个空字符串。
            loc = [str(part) for part in err["loc"][1:]]
            details.append(
                {
                    "field": ".".join(loc) or "body",
                    "message": err.get("msg", ""),
                }
            )

        return JSONResponse(
            # 用 HTTP_422_UNPROCESSABLE_CONTENT 而不是老的 ..._ENTITY：
            # RFC 9110 把这个状态码的措辞从 "Unprocessable Entity" 改成了
            # "Unprocessable Content"，新版本的 Starlette 会为老名字发弃用警告。
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "请求参数校验失败",
                    "details": details,
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # 注册 Starlette 的 HTTPException 而不是 FastAPI 的：
        # FastAPI 那个是它的子类，注册父类能同时兜住两者。
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": "http_error",
                    "message": str(exc.detail),
                }
            },
            headers=exc.headers,
        )

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        """数据库约束冲突 → 409，而不是 500。

        典型场景：POST 一篇 DOI 已经存在的论文。
        不处理的话 SQLAlchemy 的 IntegrityError 会一路冒到顶层变成 500，
        而 500 的语义是「服务端出错了」—— 可这明明是调用方传了重复数据，
        属于「客户端错误」，应该是 4xx。

        这是写接口时很容易漏的一类映射：把「数据库层异常」翻译成「HTTP 语义」。
        """
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": {
                    "code": "conflict",
                    "message": "数据冲突：唯一约束或外键约束不满足",
                }
            },
        )
