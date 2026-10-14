"""数据库工具本身的测试。

注意：所有 API 测试都通过 dependency_overrides 把 get_db 换掉了，
所以这个文件是 db/session.py 里 get_db 的**唯一**覆盖来源。
覆盖率报告上那块缺口，正是被依赖覆盖「遮住」的正常现象。
"""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from paper_manage.db.session import SessionLocal, engine, get_db


def test_get_db_yields_a_session_then_finishes() -> None:
    """直接驱动生成器：确认它产出 Session，并且走完后能正常结束。

    生成器走完意味着 finally 里的 db.close() 被执行了 —— 这正是
    「依赖用生成器写、清理放 finally」这个模式要保证的事。
    """
    generator = get_db()
    session = next(generator)
    assert isinstance(session, Session)

    with pytest.raises(StopIteration):
        next(generator)


def test_engine_can_reach_the_database() -> None:
    """engine 配置对不对，一次真实连接就能验证。

    create_engine 是**惰性**的：配置错了它不会立刻报错，
    错误会一直藏到第一次执行 SQL。所以必须主动连一次把它逼出来。
    """
    with engine.connect() as connection:
        assert connection.execute(text("select 1")).scalar() == 1


def test_session_local_settings_are_intentional() -> None:
    """这两个取值都是有原因的，别被人顺手改掉。"""
    session = SessionLocal()
    try:
        assert session.autoflush is False
        # expire_on_commit=False：commit 之后对象属性不过期。
        # 否则响应序列化时会触发额外查询，session 已关时还会抛 DetachedInstanceError。
        assert session.expire_on_commit is False
    finally:
        session.close()
