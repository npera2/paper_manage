# ---------- 构建阶段 ----------
# 只负责把依赖装进 /app/.venv。装完这个阶段整个被丢掉，不进最终镜像。
FROM python:3.12-slim-bookworm AS builder

# uv 的官方做法：直接从它的镜像里把二进制拷过来。
# 比 `pip install uv` 干净（不会在镜像里留一份 pip），也比自己下载脚本可控。
# 版本和本地 pyproject 里的 uv 对齐，避免"本地能装、容器里装不上"。
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# 先只拷依赖清单：只要这两份文件没变，下面这层就命中缓存，
# 改业务代码不会触发重新安装依赖 —— 这是分层构建最值钱的地方。
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# 再拷源码，并安装项目本身（editable，会把 src/ 挂进 .pth，
# 这样 paper_manage 才 import 得到）。
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


# ---------- 运行阶段 ----------
# 从零开始，不带构建工具链和 uv 缓存，镜像能小一大截。
FROM python:3.12-slim-bookworm

# 不用 root 跑服务：万一被突破，攻击面小得多。这是容器安全的基本要求，
# 也是很多公司在部署规范里强制要求的。
RUN useradd --create-home --uid 1000 appuser

WORKDIR /app
COPY --from=builder --chown=appuser:appuser /app /app

# 把虚拟环境放最前面，uvicorn / alembic 就能直接用，不用写全路径。
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER appuser
EXPOSE 8000

# 启动前先跑迁移，再起服务。
#
# exec 不能省：少了它，uvicorn 就不是 PID 1，容器收到的 SIGTERM 传不到它手上，
# `docker compose stop` 会退化成「等 10 秒然后强杀」，正在处理的请求会被硬切。
#
# 已知局限：多个副本同时启动时，迁移会打架。生产环境应该把迁移拆成
# 独立的部署步骤（只跑一次），而不是塞在每个容器的启动命令里。
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn paper_manage.main:app --host 0.0.0.0 --port 8000"]
