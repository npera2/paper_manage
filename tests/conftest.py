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
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from paper_manage.core.config import settings
from paper_manage.db.base import Base
from paper_manage.db.session import get_db
from paper_manage.main import app

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
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": TEST_DB_NAME},
        ).scalar()
        if not exists:
            # 库名是我们自己的常量、不是用户输入，所以 f-string 拼接安全。
            # 注意 CREATE DATABASE 不接受参数化占位符，只能拼字符串。
            conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))

    test_engine = create_engine(test_database_url, pool_pre_ping=True)

    # 只建一次表。注意这里用的是 create_all —— 它完全按模型定义建表，
    # 所以我们在开发库上手工执行过的 `CREATE INDEX ... USING gin (title gin_trgm_ops)`
    # 在测试库里是**不存在的**。这种「手写 SQL 和模型定义脱节」的问题，
    # 正是阶段 6 要引入 Alembic 的原因。
    Base.metadata.create_all(test_engine)

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
