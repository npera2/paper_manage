from fastapi import FastAPI

from paper_manage.api.routes import imports, papers

app = FastAPI()
app.include_router(papers.router)
app.include_router(imports.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
