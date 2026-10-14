# paper_manage 项目长期备忘

## 协作约定（2026-10-12 确立）

- 每个阶段的交付物格式 = **任务卡**（目标 / 要写的文件 / 操作步骤 / 验收标准 / 踩坑提示）。
- 用户明确讨厌空话，要「第一步打开哪个页面」这种颗粒度；给建议必须具体到文件名和命令。
- 项目定位 = **简历项目**，所以每个技术选型都要能讲出理由，并需加迁移、索引优化、README 包装。

### ⚠️ 交付颗粒度已于 2026-10-12 晚间上调（覆盖之前的约定）
- 原先约定「不给业务代码，只讲原理 + 验收标准」。**用户当晚明确要求改为**：
  「你要告诉我每个文件中要写入的具体内容，以及我每一步要做的具体操作，
  我目前对一些技术栈还不是很熟悉」。
- **新约定**：给出**完整可运行的文件内容** + **逐块解释** + **精确操作命令**，
  由用户自己敲进去（仍**不要**替他 Write 文件，保留动手过程）。
- 原因：用户是研一学生，对 FastAPI / SQLAlchemy / pydantic-settings 都还陌生，
  只给规格+验收会卡住。教知识靠「逐块解释」，练手靠「他自己敲」。

### 讲坑的原则（用户认可）
- **静默失败必须提前告知**（不报错的东西没有反馈，无从学起，只会浪费时间）。
- **洪亮失败留给用户自己撞**（报错本身就是最好的教材），撞了再一起分析根因。

## 技术栈（已锁定，2026-10-12）
- FastAPI + **SQLAlchemy 2.0 同步** + psycopg3（否决了 async）
- pydantic-settings 管配置；Alembic 管迁移
- 测试：pytest + httpx + fixture 起测试库；lint/format：ruff
- 交付：Dockerfile + docker-compose（api + postgres）+ GitHub Actions（push 跑 ruff + pytest）
- 包管理：uv（src-layout，uv_build 后端，Python 3.12）

## 工具配置约定
- `pyproject.toml` 的 `[tool.ruff.lint]` 里 **必须 ignore `RUF001/RUF002/RUF003`**：
  `RUF` 规则集包含 ambiguous-unicode-character，会把中文全角标点（，：！）
  在字符串/文档字符串/注释里全部标红。中文项目的标准做法就是关掉这三条。
- 同理，交付含 `__main__` 等带下划线名字的代码给用户时，要在消息里提醒
  「粘完检查有没有混进 `&#` 实体或零宽字符」——2026-10-14 用户就因此被卡住过一次。
  自查命令：`grep -rn "&#" --include="*.py" .`
- **文件上传依赖 `python-multipart`**（FastAPI 的 `File`/`UploadFile` 必需），
  已在 2026-10-14 加入生产依赖。

## 分层约定（2026-10-14 阶段 4 确立）
- `core/` 纯逻辑（不 import fastapi、不碰数据库），可直接单元测试。
  例：`core/bibtex.py` 解析器、`core/security.py` 的 key 比对。
- `schemas/` Pydantic 边界模型，负责校验与规范化（清洗只在这一层做，下游信任输入）。
- `crud/` 纯数据访问；`services/` 放跨层的业务编排（如 BibTeX 导入流程）。
- `api/routes/` 只收参数、调下层、定状态码，不写业务逻辑。

## 迁移与部署约定（阶段 6，2026-10-14）
- Alembic 管理 schema，迁移文件在 `migrations/versions/`。`alembic` 是**生产依赖**
  （容器启动要跑 `alembic upgrade head`）。
- ⚠️ **`alembic.ini` 必须纯 ASCII**。Alembic 用 `configparser.read(encoding="locale")` 读它，
  中文 Windows 的 locale 是 GBK，UTF-8 中文注释会直接
  `UnicodeDecodeError: 'gbk' codec can't decode byte 0xae`。
- `migrations/env.py` 注入 URL 时必须判断 `if not config.get_main_option("sqlalchemy.url")`，
  **不能无条件覆盖**，否则调用方（测试夹具 / CI）传的 URL 会被改回默认库。
- autogenerate 是拿 metadata 和**真实数据库**做 diff，所以生成初始迁移要在**空库**上跑。
- **已有数据的库接入 Alembic 要用 `alembic stamp head`**，不能 `upgrade head`（会撞表已存在）。
- **测试库也用 Alembic 迁移建表**（`tests/conftest.py` 里 `DROP DATABASE ... WITH (FORCE)` +
  `CREATE DATABASE` + `command.upgrade(cfg, "head")`），不用 `create_all`。
  理由：create_all 看不到迁移里的额外对象（GIN 索引），会让测试库 schema 与真实部署分叉。
- PostgreSQL 的**事务性 DDL**：迁移失败会整体回滚，不会留下半截 schema。值得写进 README。

## Docker 约定（阶段 6）
- `Dockerfile` 多阶段：builder（uv 装依赖）→ runtime（只拷结果）+ 非 root 用户 uid 1000。
  uv 二进制来自 `COPY --from=ghcr.io/astral-sh/uv:0.12.17`（版本与本地对齐）。
- CMD 是 `alembic upgrade head && exec uvicorn ...`，**`exec` 不能省**（否则 SIGTERM 传不到 uvicorn）。
- `.dockerignore` **必须排除 `.env`**（镜像层可被 pull 到的人看到），
  但**不能**排除 `migrations/` 和 `alembic.ini`。
- `docker-compose.yml`：db **不映射 5432**（走内部网络，也避开宿主机已有的 `paper-pg`）；
  `depends_on: condition: service_healthy`；api 用 `environment` 覆盖 `env_file` 的
  `DATABASE_URL` 为服务名 `db`。
- 容器里连数据库用**服务名 `db`**，不是 `localhost`。

## 测试约定（阶段 5，2026-10-14）
- 状态：**126 个测试、覆盖率 100%**，`uv run pytest` 一键跑。
- 测试库 `paper_manage_test`，与开发库物理隔离，由 `tests/conftest.py` 自动创建。
- **隔离机制**：`connection.begin()` 外层事务 + `Session(bind=connection,
  join_transaction_mode="create_savepoint")`，测试结束 `rollback()` 一锅端。
  这是 SQLAlchemy 2.0 的正统写法，别再抄老的 `after_transaction_end` 事件方案。
- `client` fixture 用 `dependency_overrides[get_db]` 指向**同一个 db_session**。
  新建 session 是最常见的坑（数据跑到另一条连接上，回滚不掉）。
- ⚠️ `make_url()` 的结果必须 `render_as_string(hide_password=False)` 再转字符串，
  否则密码变成 `***`。
- `scripts/check_source.py`（源码卫生扫描）已同步为 `tests/test_source_hygiene.py`，
  阶段 7 会随 pytest 一起进 CI。

## BibTeX 导入的约定（阶段 4）- 幂等去重：**DOI 优先**；无 DOI 时用 `(title, year)` 兜底指纹。
  去重要同时比对「库里已有的」+「同一文件里已出现过的」。
- 语义是**部分成功**：返回 200 + `ImportStats`，不变式
  `total == created + skipped + failed`，失败明细在 `issues`。
- 导入必须走 `PaperCreate` 校验，保证与手动创建同一套规则。
- `author_order` 靠 `crud._link_authors()` 手工 `insert(paper_authors)` 写入
  （relationship 自动插行时拿不到中间表的额外列）。
- **`/papers/import` 路由必须在 `papers` 之前注册**，否则被 `/papers/{paper_id}` 抢走 → 422。
- 上传接口用**同步 def** + `file.file.read()`，与同步 SQLAlchemy 栈保持一致。

## 领域模型（阶段 1 定稿，2026-10-12）Paper(id PK, title String(512) NOT NULL, abstract Text NULL, year Int NULL **索引**,
      venue String(256) NULL, doi String(128) NULL **唯一**, created_at DateTime
      server_default=now())
Author(id PK, name String(256) NOT NULL **索引**, affiliation String(256) NULL)
Tag(id PK, name String(64) NOT NULL **唯一**)
paper_authors(paper_id + author_id 复合主键，外加 **author_order** Int 记录署名顺序)
paper_tags(paper_id + tag_id 复合主键)

- 作者与标签一律走**独立表 + 关联表**（多对多），不用字符串数组 / JSON 列，
  理由：「按作者/标签检索」必须能走索引，`LIKE '%name%'` 是全表扫描 + 误匹配。
- 关联表列名用 `author_order` 而不是 `position`，避开 SQL 的 POSITION 关键字。
- 用 SQLAlchemy 2.0 风格：`Mapped[...]` + `mapped_column`（网上教程多为 1.x 的 `Column(...)` 写法，别抄）。

## 环境注意
- Windows 机器，内存偏紧（用户曾反馈装 WSL2 有困难）。
- **用户主力终端已从 cmd.exe 换成 Git Bash**（2026-10-12）。不要再用 cmd 语法给命令。
- **依赖必须写 `psycopg[binary]`，不能只写 `psycopg`**（2026-10-14 踩过）：
  psycopg3 有三个实现（`psycopg_c` 需编译 / `psycopg_binary` 自带 libpq / 纯 Python 需系统 libpq）。
  Windows 上没有 libpq.dll，只装 `psycopg` 会在 `create_engine` 时抛
  `ImportError: no pq wrapper available`。装命令：`uv add "psycopg[binary]"`（**引号必须加**，
  `[binary]` 在 bash 里是通配符）。Dockerfile 里同样要用 `psycopg[binary]`。
- **Windows + Docker 的 `localhost` 坑（已修正为「建议」而非「绝对」）**：
  本机 Docker 实际把 IPv4 和 IPv6 都映射了（`[::]:5432`），所以 `localhost` 大概率能通。
  但仍推荐 `DATABASE_URL` 主机名写 `127.0.0.1` —— Linux 服务器上 Docker 常只监听 IPv4。
- 阶段 1 起数据库用**专属容器 `paper-pg`**（postgres:16.2 / user=postgres /
  password=postgres / db=paper_manage / 卷 paper-pg-data / 端口 5432）。
  机器上另有遗留容器 `pg-study`（密码不可知，不可复用，保持停止即可）。
- Docker CLI 已装（29.8.2 + Compose v5.5.1），Docker Desktop 守护进程需手动启动。
