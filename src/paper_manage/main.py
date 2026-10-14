from fastapi import FastAPI

from paper_manage.api.routes import imports, papers
from paper_manage.core.errors import register_exception_handlers

app = FastAPI(title="Paper Manage API", version="0.1.0")

# ⚠️ 顺序有讲究：imports 必须挂在 papers 前面！
# papers 里有 /papers/{paper_id} 这种通配路径，如果它先注册，
# 请求 /papers/import 会被它抢走、把 "import" 当 paper_id 解析 → 422。
# 规则：更具体的路径必须排在通配路径前面。
app.include_router(imports.router)
app.include_router(papers.router)

# 统一错误响应格式（见 core/errors.py）
register_exception_handlers(app)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
