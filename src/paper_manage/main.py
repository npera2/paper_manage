from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from paper_manage.api.routes import auth, imports, papers
from paper_manage.core.errors import register_exception_handlers

app = FastAPI(title="Paper Manage API", version="0.1.0")

# ⚠️ 顺序有讲究：imports 必须挂在 papers 前面！
# papers 里有 /papers/{paper_id} 这种通配路径，如果它先注册，
# 请求 /papers/import 会被它抢走、把 "import" 当 paper_id 解析 → 422。
# 规则：更具体的路径必须排在通配路径前面。
app.include_router(auth.router)
app.include_router(imports.router)
app.include_router(papers.router)

# 统一错误响应格式（见 core/errors.py）
register_exception_handlers(app)

# 内置的 Web 控制台（单文件 HTML，无构建步骤、无外部依赖）。
#
# 为什么由 FastAPI 自己托管，而不是单独起一个静态服务器：
#   1. **同源，不需要配 CORS。** 如果页面和 API 不同源（换端口、或直接双击
#      打开 html 文件），浏览器会在发请求前就把跨域请求拦掉，必须加
#      CORSMiddleware 并仔细想清楚 allow_origins 该开多大 —— 这里直接绕开了整件事。
#   2. docker compose 起来之后立刻就能用，不用再多起一个服务、多记一个端口。
#
# 路径用 Path(__file__).parent 定位，不写相对路径：相对路径是按「进程工作目录」
# 解析的，本地和容器里的工作目录不同，迟早会错。
_WEB_DIR = Path(__file__).parent / "web"
app.mount("/ui", StaticFiles(directory=_WEB_DIR, html=True), name="ui")


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    """根路径直接跳到控制台，省得用户猜地址。"""
    return RedirectResponse(url="/ui/")
