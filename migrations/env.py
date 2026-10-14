"""Alembic 的运行环境配置。

这个文件回答三个问题：
  1. 连哪个库？—— 从应用自己的配置里读，不在这里写死
  2. 拿什么当「目标 schema」？—— 模型的 metadata
  3. 离线 / 在线两种模式各自怎么跑？
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ⚠️ 这一行必须留！它触发所有模型类的定义，从而把表注册进 Base.metadata。
# 少了它 Base.metadata 是空的，autogenerate 会认为「数据库里现有的表都该被删掉」，
# 于是生成一份删库迁移 —— 这是 Alembic 最经典的事故。
import paper_manage.models  # noqa: F401
from paper_manage.core.config import settings
from paper_manage.db.base import Base

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False 不能省：默认值是 True，会把已经配置好的
    # logger 全部关掉。测试夹具里会调用迁移，默认行为会把 pytest 的日志捕获搞坏。
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# 把连接串从应用配置注入进来 —— 但**只在调用方没给的时候**。
#
# 为什么必须判断：测试夹具、CI 脚本这类调用方会用 config.set_main_option
# 主动传入自己的库。如果这里无条件覆盖，就会把它们传的值改回默认库，
# 于是迁移跑到错误的数据库上（我们在阶段 6 真的踩过一次：测试夹具传了测试库，
# 结果迁移跑去了开发库，撞上"表已存在"而失败）。
#
# 注意 .replace("%", "%%")：ConfigParser 把 % 当插值符号，
# 密码里一旦出现 %（URL 编码后的特殊字符很常见）不转义就会直接报错。
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

# autogenerate 就是拿这个 metadata 和真实数据库做 diff
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL 文本，完全不连数据库。

    用 `alembic upgrade head --sql` 走这条路，
    产出的纯 SQL 可以直接交给 DBA 审阅后再执行。
    """
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：真的连库、真的执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        # NullPool：迁移是一次性任务，跑完就退出，不需要连接池
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # compare_type=True：字段类型变了也算差异。
            # 默认是关的，不开的话你会漏掉「String(100) 改成 String(200)」这类变更 ——
            # 而且是静默漏掉，只有等到线上报错才发现。
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
