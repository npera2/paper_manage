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
