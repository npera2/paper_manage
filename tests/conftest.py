"""pytest 的公共 fixture。

这里最需要理解的是**数据库隔离**：怎么保证每个测试都从干净状态开始，
又不必每个测试都重建一次表结构（那会慢到无法忍受）。

答案是「外层事务 + SAVEPOINT」：
  1. 整个测试会话只建一次表（session 级 fixture）；
  2. 每个测试开一条连接、启一个事务，但**永不提交**；
  3. 被测代码里的 session.commit() 只是释放 SAVEPOINT、再开一个新的，
     最外层那个事务始终没结束；
  4. 测试结束直接把外层事务 rollback → 数据全部消失。

于是每个测试都是干净的，平均代价只有一次 rollback，比「每个测试 drop_all + create_all」
快一到两个数量级。
"""

from collections.abc import Callable, Iterator
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from paper_manage.core.config import settings
from paper_manage.db.session import get_db
from paper_manage.main import app

# 项目根目录，用来定位 alembic.ini 和 migrations/
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 测试库和开发库**物理隔离**。
# 绝不能让测试跑在有真实数据的库上 —— 测试会造数据、也会删数据。
TEST_DB_NAME = "paper_manage_test"

# 测试里反复用到的合法请求体，放模块级常量方便各测试改造变体
DEFAULT_PAPER: dict[str, Any] = {
    "title": "Subglacial valley mapping in East Antarctica",
    "abstract": "We map subglacial valleys from radio-echo sounding data.",
    "year": 2024,
    "venue": "The Cryosphere",
    "doi": "10.5194/tc-2024-001",
    "authors": [
        {"name": "Alice Zhang", "affiliation": "Polar Institute"},
        {"name": "Bob Li", "affiliation": "Ocean University"},
    ],
    "tags": ["glaciology", "valley"],
}


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """测试库的连接串：拿开发库的连接串换个库名就行。"""
    # render_as_string(hide_password=False) 不能省。
    # SQLAlchemy 的 URL 默认会把密码渲染成 `***`，直接 str() 出来的连接串连不上库。
    url = make_url(settings.database_url).set(database=TEST_DB_NAME)
    return url.render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def admin_engine() -> Iterator[Engine]:
    """用来建测试库的引擎，连到 PostgreSQL 自带的 postgres 维护库。

    CREATE DATABASE 不能在事务里执行，所以必须用 AUTOCOMMIT 隔离级别。
    """
    admin_url = make_url(settings.database_url).set(database="postgres")
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def engine(test_database_url: str, admin_engine: Engine) -> Iterator[Engine]:
    """确保测试库存在，返回连到测试库的引擎，并在库里建好表。"""
    with admin_engine.connect() as conn:
        # 每次测试会话都整个删库重建。WITH (FORCE) 会顺手踢掉还挂着的旧连接，
        # 否则 DROP 会因为「有客户端正在使用这个库」而失败。
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))

    # 用 Alembic 迁移建表，而不是 Base.metadata.create_all()。
    #
    # 这个区别很重要：create_all 只按模型定义建表，看不到迁移里额外做的事
    # （比如那个 pg_trgm 的 GIN 索引）。拿它建测试库，测试库的 schema 就会
    # 和真实部署悄悄分叉 —— 迁移写错了测试照样全绿，直到线上才发现。
    # 用同一套迁移建库，测试才是真的在验证「线上会是什么样」。
    alembic_config = Config(str(PROJECT_ROOT / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    # 同样的 % 转义问题：ConfigParser 会把 % 当插值符号
    alembic_config.set_main_option("sqlalchemy.url", test_database_url.replace("%", "%%"))
    command.upgrade(alembic_config, "head")

    test_engine = create_engine(test_database_url, pool_pre_ping=True)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    """每个测试一个 session，绑在一个永不提交的外层事务上。"""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        # 这个参数是本文件的核心。
        # 不加它：被测代码里的 session.commit() 会把外层事务一起提交（数据真写进库了），
        #         测试之间就会互相污染，而且脏数据留在测试库里清不掉。
        # 加上它：commit 变成「释放 SAVEPOINT，再开一个新的」，
        #         外层事务始终未结束，最后 rollback 一锅端。
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    """测试用 HTTP 客户端，把应用的数据库依赖替换成测试 session。

    app.dependency_overrides 是 FastAPI 提供的替换机制：把 get_db 这个
    「依赖函数」映射成别的实现，所有用到它的路由就都拿到替换后的东西，
    业务代码一行都不用改。
    """

    def override_get_db() -> Iterator[Session]:
        # 这里 yield 的是同一个 db_session，不是新建一个 session。
        # 如果在这里 SessionLocal() 新建，数据就跑到另一条连接上去了：
        # 测试里查不到、回滚也回滚不掉、还会把脏数据留进测试库。
        # 这是自建 fixture 时最常见的坑。
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """带正确 API Key 的请求头。"""
    return {"X-API-Key": settings.api_key}


@pytest.fixture
def paper_payload() -> dict[str, Any]:
    """一份合法的请求体。返回的是**深拷贝**，测试随便改，不会影响其他测试。"""
    return deepcopy(DEFAULT_PAPER)


@pytest.fixture
def create_paper(client: TestClient, auth_headers: dict[str, str]) -> Callable[..., dict]:
    """建一篇论文并返回响应 JSON，让测试的意图更清楚。

    用法：paper = create_paper()            用默认数据
          paper = create_paper(year=1999)   覆盖某个字段
    """

    def _create(**overrides: Any) -> dict:
        response = client.post(
            "/papers",
            json={**DEFAULT_PAPER, **overrides},
            headers=auth_headers,
        )
        # 这里断言是为了：如果前置条件都挂了，后面的失败信息会指向真正的原因，
        # 而不是在某个看似无关的地方报 KeyError。
        assert response.status_code == 201, response.text
        return response.json()

    return _create
