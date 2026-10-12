# paper_manage 项目长期备忘

## 协作约定（2026-10-12 确立，不可违反）
- **不要直接给业务代码**。用户要自己写。我的职责是：讲原理 → 给验收标准 → 逐行 review。
- 每个阶段的交付物格式 = **任务卡**（目标 / 要写的文件 / 验收标准 / 让他自己撞的坑）。
- 用户明确讨厌空话，要「第一步打开哪个页面」这种颗粒度；给建议必须具体到文件名和命令。
- 项目定位 = **简历项目**，所以每个技术选型都要能讲出理由，并需加迁移、索引优化、README 包装。

## 技术栈（已锁定，2026-10-12）
- FastAPI + **SQLAlchemy 2.0 同步** + psycopg3（否决了 async）
- pydantic-settings 管配置；Alembic 管迁移
- 测试：pytest + httpx + fixture 起测试库；lint/format：ruff
- 交付：Dockerfile + docker-compose（api + postgres）+ GitHub Actions（push 跑 ruff + pytest）
- 包管理：uv（src-layout，uv_build 后端，Python 3.12）

## 领域模型设想
Paper(title, abstract, year, venue, doi, created_at) / Author / Tag。
作者与标签用**独立表 + 关联表**（多对多），检索依赖规范化字段上的索引。

## 环境注意
- Windows 机器，内存偏紧（用户曾反馈装 WSL2 有困难）。
- Docker CLI 已装（29.8.2 + Compose v5.5.1），但 Docker Desktop 守护进程需用户手动启动。
