# Session 数据标准化 + Postgres 迁移 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `sessions(data BLOB)` 单表拆成关系模型（`sessions` / `utterances` / `suggestions` / `profile_entries`），后端切换到 PostgreSQL，前端通过新增的 history API 实现刷新回放。

**Architecture:**
- 关系模型四张表替代 BLOB；`Utterance.id` / `request_id` 升级为外键，保证全局贯通。
- Agent runtime 状态（`pending` / `inflight` / `generation`）只留在内存，崩溃即重建——本来就不该跨进程持久化。
- SQLAlchemy 2.0 async ORM + psycopg3 异步驱动 + alembic 管理 schema。
- `ContextStore` 改为"写穿 DB + 内存缓存"：写路径持久化，读路径走缓存，启动时从 DB hydrate。
- 旧 `sessions.db` 直接丢弃（开发期 reset），不写迁移脚本。

**Tech Stack:** PostgreSQL 16, SQLAlchemy 2.0 async, psycopg[binary], alembic, docker-compose

**Out of scope:**
- Agno 自身的 `agno.db`（框架内部状态，单独管）
- 律师声纹的多用户化（继续用文件单例 + per-session deepcopy）
- 客户声纹（`client_embedding`）的跨刷新恢复——刷新后允许重新自举，前几句 speaker 可能 `uncertain`，可接受
- 现有 BLOB 数据迁移

---

## 范围确认

| 维度 | 决策 |
|---|---|
| 数据库 | Postgres 16 + asyncpg 风格异步（用 psycopg3 async） |
| ORM | SQLAlchemy 2.0 async + alembic |
| Enrollment 持久化 | **不持久化**——刷新后律师声纹用单例重建，客户声纹重新自举 |
| Pending request 持久化 | **不持久化**——继续遵循 `Orchestrator.from_dict` 原有约定 |
| 旧数据 | 丢弃，启动时建空表 |
| 前端 hydration | 包含：进入页面先 `GET /api/sessions/{sid}/history`，再连 WS |

---

## File Structure

```
backend/
├── docker-compose.yml                          # 新增：postgres 服务
├── alembic.ini                                 # 新增
├── alembic/                                    # 新增
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 0001_initial.py
├── src/
│   ├── db/                                     # 新增整层
│   │   ├── __init__.py
│   │   ├── engine.py                           # async engine + session factory
│   │   ├── base.py                             # DeclarativeBase
│   │   └── models.py                           # 四张表 ORM 模型
│   ├── repositories/                           # 新增整层
│   │   ├── __init__.py
│   │   ├── sessions.py
│   │   ├── utterances.py
│   │   ├── suggestions.py
│   │   └── profile_entries.py
│   ├── session/
│   │   ├── manager.py                          # 改造：移除 BLOB 路径
│   │   ├── models.py                           # 改造：SessionState 字段精简
│   │   ├── persistence.py                      # 删除
│   │   └── serializer.py                       # 删除
│   └── agent/
│       ├── context_store.py                    # 改造：写穿 DB
│       └── orchestrator.py                     # 改造：from_db 替代 from_dict
├── main.py                                     # 改造：持久化 suggestion 回调；DB 初始化
└── tests/                                      # 改造：fixture 切到内存 SQLite + future-compat
```

```
frontend/src/
├── api/sessions.ts                             # 新增：history API client
├── pages/LiveSession.tsx                       # 改造：mount 时拉 history
└── hooks/useWebSocket.ts                       # 微调：onSuggestion 用 request_id 而非 randomUUID
```

---

## Schema 详细定义

```sql
-- 0001_initial.py 等价 SQL（实际由 SQLAlchemy 生成）

-- 会话主表：一行 = 一次律师与客户的会谈
CREATE TABLE sessions (
    id              UUID PRIMARY KEY,                          -- 会话唯一 ID，由后端生成，前端用作 WS 路径参数
    lawyer_id       TEXT NOT NULL DEFAULT 'lawyer-default',    -- 律师身份；当前单律师，预留多用户字段
    status          TEXT NOT NULL,                             -- 生命周期：'active'（WS 已连）/ 'disconnected'（WS 断开等待重连）/ 'closed'（律师主动结束）
    summary         TEXT,                                      -- 会话结束后由 AI 生成的整段摘要，关闭前为 NULL
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),        -- 会话创建时间（POST /api/sessions 时刻）
    last_active_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),        -- 最后活跃时间；TTL 清理依据
    closed_at       TIMESTAMPTZ                                -- 关闭时间；status='closed' 时填充
);
-- 加速 TTL 清理任务：扫描 disconnected 且 last_active_at 超过阈值的会话
CREATE INDEX idx_sessions_status_lastactive ON sessions(status, last_active_at);


-- 发言流水：一行 = 一句话（由 VAD/SCD 切分出的 utterance）
CREATE TABLE utterances (
    id              TEXT PRIMARY KEY,                          -- 沿用 STT 层生成的 utterance ID（字符串格式），WS 与 DB 全程贯通同一 ID
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,   -- 所属会话；会话删除时级联清理
    seq             INTEGER NOT NULL,                          -- 在会话内单调递增的序号，刷新后按 seq 排序保证发言顺序
    text            TEXT NOT NULL,                             -- 识别出的文本内容
    t_start         DOUBLE PRECISION NOT NULL,                 -- 相对会话起点的开始秒数（音频时间轴）
    t_end           DOUBLE PRECISION NOT NULL,                 -- 相对会话起点的结束秒数
    speaker         TEXT,                                      -- 说话人：'lawyer' / 'client' / 'uncertain'，NULL 表示声纹尚未算完
    closed_by       TEXT NOT NULL,                             -- 句尾切分原因：'vad'（静音）/ 'soft_cap'（超长强切）/ 'scd'（说话人切换）
    content_hash    TEXT NOT NULL,                             -- 文本 sha1[:12]，用作 Agent 调用的缓存/去重键
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),        -- 入库时间（≠ 发言时间，发言时间看 t_start）
    UNIQUE (session_id, seq)                                   -- 防止并发 append 重号
);
-- 加速按会话拉取并排序：hydration API 与 ContextStore.hydrate() 用
CREATE INDEX idx_utterances_session_seq ON utterances(session_id, seq);


-- AI 建议：一行 = 一次 Agent 对某条 utterance 的回应
CREATE TABLE suggestions (
    id              UUID PRIMARY KEY,                          -- 主键，仅用作 DB 内部唯一标识
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,   -- 所属会话；级联删除
    utt_id          TEXT NOT NULL REFERENCES utterances(id) ON DELETE CASCADE, -- 触发本次建议的 utterance；级联删除（utterance 没了建议也没意义）
    request_id      TEXT NOT NULL,                             -- Orchestrator 生成的请求 ID，前端拿来去重 + pending→ready 状态合并
    kind            TEXT NOT NULL,                             -- 状态：'pending'（律师待确认）/ 'ready'（已生成正式答案）
    preview_topic   TEXT,                                      -- pending 阶段展示给律师的话题预览（"是否要分析X方面"）
    preview_rationale TEXT,                                    -- pending 阶段的简短理由说明
    text            TEXT,                                      -- ready 阶段的完整答案；pending 时为 NULL
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),        -- 首次出现时间（pending 进入或直接 ready）
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),        -- pending→ready 升级时刷新
    UNIQUE (session_id, request_id)                            -- 业务幂等键：同一 request_id 在会话内只有一行，pending/ready 通过 upsert 更新
);
-- 加速 history API：按会话拉建议并按时序展示
CREATE INDEX idx_suggestions_session_created ON suggestions(session_id, created_at);


-- 客户画像条目：一行 = 从对话中提取的一条法律事实
CREATE TABLE profile_entries (
    id              UUID PRIMARY KEY,                          -- 主键
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,   -- 所属会话；级联删除
    source_utt_id   TEXT REFERENCES utterances(id) ON DELETE SET NULL,         -- 提取自哪条 utterance；utterance 删除时置 NULL（保留事实本身）
    key             TEXT NOT NULL,                             -- 事实字段名（如 "职业"、"婚姻状况"）
    value           TEXT NOT NULL,                             -- 事实值（如 "教师"、"已婚"）
    timestamp       DOUBLE PRECISION NOT NULL,                 -- 事实出现的音频秒数（沿用 ProfileEntry.timestamp 语义，非 datetime）
    confidence      DOUBLE PRECISION NOT NULL DEFAULT 1.0,     -- ProfileAgent 提取的置信度
    category        TEXT,                                      -- 可选分类（如 "身份信息"、"诉求"），便于前端分组展示
    subject         TEXT NOT NULL DEFAULT '',                  -- 事实归属主体："本人" / "对方" / "第三方"；空串表示未标注
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()         -- 入库时间
);
-- 加速按会话拉画像并按事实出现顺序展示
CREATE INDEX idx_profile_session_timestamp ON profile_entries(session_id, timestamp);
```

**关键决策注释：**
- `utterances.id` 用 TEXT 保留 STT 现有 ID 格式（避免改 STT 层）。
- `utterances.seq` 替代"在 list 中的下标"做有序查询，同时作为唯一性约束防重复 append。
- `suggestions(session_id, request_id)` 唯一索引——`request_id` 是 Orchestrator 生成的幂等键，前端拿它去重。
- `enrollments` 表**不创建**——刷新后律师声纹用单例重建，客户声纹重新自举。

---

## Task 1: 加 Postgres 依赖与 docker-compose

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/docker-compose.yml`
- Modify: `backend/.env.example`

- [ ] **Step 1: 添加依赖到 pyproject.toml**

打开 `backend/pyproject.toml`，在 `dependencies = [...]` 列表末尾加：

```toml
    "alembic>=1.13.0",
```

`sqlalchemy>=2.0.0` 和 `psycopg[binary]>=3.1.0` 已存在，不重复加。psycopg3 内置 async，不需要 asyncpg。

- [ ] **Step 2: 同步依赖**

Run: `cd backend && uv sync`
Expected: `alembic` 安装成功；其他包无变化。

- [ ] **Step 3: 创建 docker-compose.yml**

Create `backend/docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: legal_agent
      POSTGRES_PASSWORD: legal_agent_dev
      POSTGRES_DB: legal_agent
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U legal_agent"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  pgdata:
```

- [ ] **Step 4: 更新 .env.example**

在 `backend/.env.example` 末尾追加：

```
# Postgres 连接（dev 默认指向 docker-compose）
DATABASE_URL=postgresql+psycopg://legal:legal@localhost:5432/legal_agent
```

- [ ] **Step 5: 启动 Postgres 验证**

Run: `cd backend && docker compose up -d postgres && docker compose ps`
Expected: postgres 容器 healthy 状态。

- [ ] **Step 6: 提交**

```bash
git add backend/pyproject.toml backend/uv.lock backend/docker-compose.yml backend/.env.example
git commit -m "feat(db): 添加 Postgres 与 alembic 依赖"
```

---

## Task 2: SQLAlchemy 异步 engine 与 base

**Files:**
- Create: `backend/src/db/__init__.py`
- Create: `backend/src/db/base.py`
- Create: `backend/src/db/engine.py`
- Create: `backend/tests/db/test_engine.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/db/test_engine.py`:

```python
"""测试 async engine 能与真实 Postgres 建立连接并执行简单查询。"""
import os
import pytest
from sqlalchemy import text

from db.engine import create_engine_from_env, get_sessionmaker


@pytest.mark.asyncio
async def test_engine_connects_to_postgres():
    """engine 能连上 Postgres 并执行 SELECT 1——验证连接串与驱动配置正确。"""
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql+psycopg://legal:legal@localhost:5432/legal_agent",
    )
    engine = create_engine_from_env()
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        assert result.scalar_one() == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_sessionmaker_yields_async_session():
    """session 工厂能产出可用的 AsyncSession——避免 maker 配置写错。"""
    engine = create_engine_from_env()
    SessionLocal = get_sessionmaker(engine)
    async with SessionLocal() as session:
        result = await session.execute(text("SELECT 2"))
        assert result.scalar_one() == 2
    await engine.dispose()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/db/test_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'db'`

- [ ] **Step 3: 实现 base.py**

Create `backend/src/db/__init__.py` (空文件) 与 `backend/src/db/base.py`:

```python
"""SQLAlchemy DeclarativeBase 入口；所有 ORM model 继承自 Base。"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

- [ ] **Step 4: 实现 engine.py**

Create `backend/src/db/engine.py`:

```python
"""Async SQLAlchemy engine + sessionmaker 工厂。"""
import os

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine_from_env() -> AsyncEngine:
    """从 DATABASE_URL 环境变量创建 async engine。缺失时显式抛错——配置错误必须立刻显现。"""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return create_async_engine(url, pool_pre_ping=True, future=True)


def get_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """构造 async session 工厂；expire_on_commit=False 让对象在事务外仍可用。"""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && docker compose up -d postgres && uv run pytest tests/db/test_engine.py -v`
Expected: PASS（前提是 postgres 容器已启动）

- [ ] **Step 6: 提交**

```bash
git add backend/src/db backend/tests/db
git commit -m "feat(db): SQLAlchemy async engine 与 sessionmaker 工厂"
```

---

## Task 3: 初始化 alembic

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/.gitkeep`

- [ ] **Step 1: 生成 alembic 脚手架**

Run: `cd backend && uv run alembic init alembic`
Expected: 生成 `alembic.ini` 和 `alembic/` 目录。

- [ ] **Step 2: 改写 alembic/env.py 使用项目 engine**

Open `backend/alembic/env.py`，把整个文件替换为：

```python
"""Alembic 环境：用项目 async engine + Base.metadata。"""
import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from db.base import Base  # noqa: E402
import db.models  # noqa: E402,F401  # 触发 ORM 注册到 metadata

config = context.config

if config.config_file_name:
    fileConfig(config.config_file_name)

if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])

target_metadata = Base.metadata


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


run_migrations_online()
```

- [ ] **Step 3: alembic.ini 改 script_location 与 URL**

Open `backend/alembic.ini`，确认：

```ini
[alembic]
script_location = alembic
sqlalchemy.url =
```

`sqlalchemy.url` 留空——由 env.py 从环境变量注入。

- [ ] **Step 4: 验证 alembic 能连库（暂无 migration）**

Run: `cd backend && DATABASE_URL=postgresql+psycopg://legal:legal@localhost:5432/legal_agent uv run alembic current`
Expected: 输出空（没有版本记录）但不报错。

- [ ] **Step 5: 提交**

```bash
git add backend/alembic.ini backend/alembic
git commit -m "feat(db): 初始化 alembic 配置"
```

---

## Task 4: ORM models 定义

**Files:**
- Create: `backend/src/db/models.py`
- Create: `backend/tests/db/test_models.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/db/test_models.py`:

```python
"""验证 ORM 模型字段、约束、外键关系，避免迁移后查询时才发现 schema 漏。"""
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db.engine import create_engine_from_env, get_sessionmaker
from db.models import ProfileEntry, Session, Suggestion, Utterance


@pytest.mark.asyncio
async def test_session_roundtrip(db_session):
    """插入与查询 session——验证主键/默认值/状态字段全部生效。"""
    sid = uuid.uuid4()
    db_session.add(Session(id=sid, status="active"))
    await db_session.commit()
    fetched = (await db_session.execute(select(Session).where(Session.id == sid))).scalar_one()
    assert fetched.status == "active"
    assert fetched.lawyer_id == "lawyer-default"


@pytest.mark.asyncio
async def test_utterance_session_fk(db_session):
    """utterance.session_id 引用不存在的 session 必须抛 IntegrityError——验证外键约束。"""
    db_session.add(Utterance(
        id="utt-1", session_id=uuid.uuid4(), seq=1, text="hi",
        t_start=0.0, t_end=0.5, closed_by="vad", content_hash="abc",
    ))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_utterance_seq_unique_per_session(db_session):
    """同一 session 下重复 seq 必须冲突——防止并发 append 重号。"""
    sid = uuid.uuid4()
    db_session.add(Session(id=sid, status="active"))
    db_session.add(Utterance(
        id="utt-a", session_id=sid, seq=1, text="a",
        t_start=0, t_end=0.1, closed_by="vad", content_hash="h1",
    ))
    await db_session.commit()
    db_session.add(Utterance(
        id="utt-b", session_id=sid, seq=1, text="b",
        t_start=0.1, t_end=0.2, closed_by="vad", content_hash="h2",
    ))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_suggestion_request_id_unique(db_session):
    """同 session 下重复 request_id 必须冲突——保证幂等键唯一性。"""
    sid = uuid.uuid4()
    db_session.add(Session(id=sid, status="active"))
    db_session.add(Utterance(
        id="utt-1", session_id=sid, seq=1, text="t",
        t_start=0, t_end=0.1, closed_by="vad", content_hash="h",
    ))
    await db_session.commit()
    db_session.add(Suggestion(
        id=uuid.uuid4(), session_id=sid, utt_id="utt-1",
        request_id="req-1", kind="pending",
    ))
    await db_session.commit()
    db_session.add(Suggestion(
        id=uuid.uuid4(), session_id=sid, utt_id="utt-1",
        request_id="req-1", kind="ready", text="ok",
    ))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_profile_entry_source_utt_set_null(db_session):
    """删除 utterance 后 profile.source_utt_id 变 NULL——避免悬空外键。"""
    sid = uuid.uuid4()
    db_session.add(Session(id=sid, status="active"))
    db_session.add(Utterance(
        id="utt-x", session_id=sid, seq=1, text="t",
        t_start=0, t_end=0.1, closed_by="vad", content_hash="h",
    ))
    entry = ProfileEntry(
        id=uuid.uuid4(), session_id=sid, source_utt_id="utt-x",
        key="职业", value="律师", timestamp=0.0, subject="本人",
    )
    db_session.add(entry)
    await db_session.commit()
    await db_session.delete((await db_session.get(Utterance, "utt-x")))
    await db_session.commit()
    await db_session.refresh(entry)
    assert entry.source_utt_id is None
```

Create `backend/tests/conftest.py`（或追加，若已存在）:

```python
"""共享 fixture：db_session 提供一个干净的事务化 AsyncSession。

每个测试用新的 engine + 建表 + 拆表，避免污染。生产用 alembic 管理 schema；
测试用 Base.metadata.create_all 跳过迁移以加速。
"""
import os

import pytest_asyncio

from db.base import Base
from db.engine import create_engine_from_env, get_sessionmaker
import db.models  # noqa: F401


@pytest_asyncio.fixture
async def db_session():
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql+psycopg://legal:legal@localhost:5432/legal_agent",
    )
    engine = create_engine_from_env()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = get_sessionmaker(engine)
    async with SessionLocal() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/db/test_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'Session' from 'db.models'`

- [ ] **Step 3: 实现 ORM 模型**

Create `backend/src/db/models.py`:

```python
"""ORM 模型 — 四张关系表。

约定：
- `Session.id` 用 UUID 主键；`Utterance.id` 沿用 STT 生成的字符串 ID。
- `created_at` / `updated_at` 由 DB 默认值填充，不写业务字段。
- 外键级联：sessions 删除时所有子表一起清；profile_entries 的 source_utt_id 用 SET NULL 避免悬空。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    lawyer_id: Mapped[str] = mapped_column(String, nullable=False, default="lawyer-default")
    status: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Utterance(Base):
    __tablename__ = "utterances"
    __table_args__ = (UniqueConstraint("session_id", "seq", name="uq_utt_session_seq"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    t_start: Mapped[float] = mapped_column(Float, nullable=False)
    t_end: Mapped[float] = mapped_column(Float, nullable=False)
    speaker: Mapped[str | None] = mapped_column(String)
    closed_by: Mapped[str] = mapped_column(String, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Suggestion(Base):
    __tablename__ = "suggestions"
    __table_args__ = (
        UniqueConstraint("session_id", "request_id", name="uq_sug_session_req"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    utt_id: Mapped[str] = mapped_column(
        String, ForeignKey("utterances.id", ondelete="CASCADE"), nullable=False
    )
    request_id: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    preview_topic: Mapped[str | None] = mapped_column(Text)
    preview_rationale: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProfileEntry(Base):
    __tablename__ = "profile_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_utt_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("utterances.id", ondelete="SET NULL")
    )
    key: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    category: Mapped[str | None] = mapped_column(String)
    subject: Mapped[str] = mapped_column(String, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/db/test_models.py -v`
Expected: 5 个测试 PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/src/db/models.py backend/tests/db/test_models.py backend/tests/conftest.py
git commit -m "feat(db): ORM 模型（sessions/utterances/suggestions/profile_entries）"
```

---

## Task 5: 初始 alembic migration

**Files:**
- Create: `backend/alembic/versions/0001_initial.py`

- [ ] **Step 1: 让 alembic 自动生成 migration**

Run: `cd backend && DATABASE_URL=postgresql+psycopg://legal:legal@localhost:5432/legal_agent uv run alembic revision --autogenerate -m "initial schema"`
Expected: 在 `alembic/versions/` 下生成一个新文件，包含四张表的 `op.create_table(...)`。

- [ ] **Step 2: 重命名为 0001_initial.py**

把刚生成的文件重命名为 `backend/alembic/versions/0001_initial.py`（保留文件内的 revision/down_revision 字段不动）。

- [ ] **Step 3: 阅读生成内容确认无误**

打开 `backend/alembic/versions/0001_initial.py`，确认：
- 四张表都有
- `unique constraints`、`indexes`、`foreign keys` 全部存在
- `down_revision = None`（第一个 migration）

如生成的索引名与 schema 定义不一致，手动调整为：`idx_sessions_status_lastactive`、`idx_utterances_session_seq`、`idx_suggestions_session_created`、`idx_profile_session_timestamp`。

- [ ] **Step 4: 跑 migration 到 Postgres**

```bash
cd backend
docker compose exec postgres psql -U legal_agent -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
DATABASE_URL=postgresql+psycopg://legal:legal@localhost:5432/legal_agent uv run alembic upgrade head
docker compose exec postgres psql -U legal_agent -c "\dt"
```
Expected: 列出 `alembic_version`、`profile_entries`、`sessions`、`suggestions`、`utterances` 五张表。

- [ ] **Step 5: 提交**

```bash
git add backend/alembic/versions/0001_initial.py
git commit -m "feat(db): 初始 schema migration"
```

---

## Task 6: SessionRepository

**Files:**
- Create: `backend/src/repositories/__init__.py`
- Create: `backend/src/repositories/sessions.py`
- Create: `backend/tests/repositories/test_sessions.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/repositories/test_sessions.py`:

```python
"""验证 SessionRepository 的 CRUD 行为，确认调用方拿到的是真值源。"""
import uuid

import pytest

from repositories.sessions import SessionRepository


@pytest.mark.asyncio
async def test_create_returns_session_with_active_status(db_session):
    """create 后立即查得到，status 默认 active——验证默认值与可见性。"""
    repo = SessionRepository(db_session)
    sid = await repo.create()
    fetched = await repo.get(sid)
    assert fetched is not None
    assert fetched.status == "active"


@pytest.mark.asyncio
async def test_set_status_persists(db_session):
    """set_status 写入后查询能读到——验证更新路径。"""
    repo = SessionRepository(db_session)
    sid = await repo.create()
    await repo.set_status(sid, "disconnected")
    fetched = await repo.get(sid)
    assert fetched.status == "disconnected"


@pytest.mark.asyncio
async def test_get_unknown_returns_none(db_session):
    """查不存在的 session 返回 None，不抛异常——调用方据此判断是否需创建。"""
    repo = SessionRepository(db_session)
    assert await repo.get(uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_set_summary_persists(db_session):
    """set_summary 可写入 None 和字符串——AI 摘要正常生成时填字符串，失败时保持 None。"""
    repo = SessionRepository(db_session)
    sid = await repo.create()
    await repo.set_summary(sid, "测试摘要")
    fetched = await repo.get(sid)
    assert fetched.summary == "测试摘要"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/repositories/test_sessions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'repositories'`

- [ ] **Step 3: 实现 SessionRepository**

Create `backend/src/repositories/__init__.py` (空) 与 `backend/src/repositories/sessions.py`:

```python
"""Session 仓储：封装 sessions 表的 CRUD。

设计：每个方法一次原子操作 + commit；调用方不需要管事务边界。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Session


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(self, *, session_id: uuid.UUID | None = None) -> uuid.UUID:
        sid = session_id or uuid.uuid4()
        self._s.add(Session(id=sid, status="active"))
        await self._s.commit()
        return sid

    async def get(self, session_id: uuid.UUID) -> Session | None:
        return await self._s.get(Session, session_id)

    async def set_status(self, session_id: uuid.UUID, status: str) -> None:
        row = await self._s.get(Session, session_id)
        if row is None:
            return
        row.status = status
        row.last_active_at = datetime.now(timezone.utc)
        if status == "closed":
            row.closed_at = datetime.now(timezone.utc)
        await self._s.commit()

    async def set_summary(self, session_id: uuid.UUID, summary: str | None) -> None:
        row = await self._s.get(Session, session_id)
        if row is None:
            return
        row.summary = summary
        await self._s.commit()

    async def touch(self, session_id: uuid.UUID) -> None:
        row = await self._s.get(Session, session_id)
        if row is None:
            return
        row.last_active_at = datetime.now(timezone.utc)
        await self._s.commit()

    async def list_expired_disconnected(self, ttl_seconds: float) -> list[uuid.UUID]:
        """返回 disconnected 且超过 TTL 的 session_id；供清理任务使用。"""
        from sqlalchemy import and_

        cutoff = datetime.now(timezone.utc).timestamp() - ttl_seconds
        stmt = select(Session.id).where(
            and_(
                Session.status == "disconnected",
                Session.last_active_at < datetime.fromtimestamp(cutoff, tz=timezone.utc),
            )
        )
        return list((await self._s.execute(stmt)).scalars().all())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/repositories/test_sessions.py -v`
Expected: 4 个测试 PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/src/repositories backend/tests/repositories/test_sessions.py
git commit -m "feat(repo): SessionRepository CRUD"
```

---

## Task 7: UtteranceRepository

**Files:**
- Create: `backend/src/repositories/utterances.py`
- Create: `backend/tests/repositories/test_utterances.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/repositories/test_utterances.py`:

```python
"""验证 utterance 仓储：追加自动分配 seq，列表按时序返回。"""
import pytest

from models.utterance import Utterance
from repositories.sessions import SessionRepository
from repositories.utterances import UtteranceRepository


def _utt(uid: str, t: float) -> Utterance:
    return Utterance(id=uid, text=f"t{uid}", t_start=t, t_end=t + 0.1, closed_by="vad")


@pytest.mark.asyncio
async def test_append_assigns_increasing_seq(db_session):
    """连续 append 的 seq 单调递增——保证 list_by_session 能稳定排序。"""
    sid = await SessionRepository(db_session).create()
    repo = UtteranceRepository(db_session)
    s1 = await repo.append(sid, _utt("u1", 0.0))
    s2 = await repo.append(sid, _utt("u2", 1.0))
    assert s2 == s1 + 1


@pytest.mark.asyncio
async def test_list_returns_in_seq_order(db_session):
    """list_by_session 必须按 seq 升序——刷新页面后用户看到的顺序与说话顺序一致。"""
    sid = await SessionRepository(db_session).create()
    repo = UtteranceRepository(db_session)
    await repo.append(sid, _utt("u1", 0.0))
    await repo.append(sid, _utt("u2", 1.0))
    items = await repo.list_by_session(sid)
    assert [u.id for u in items] == ["u1", "u2"]


@pytest.mark.asyncio
async def test_list_empty_for_unknown_session(db_session):
    """陌生 session_id 返回空列表，不抛异常——hydration API 才能用统一空数组应答。"""
    import uuid as _u
    repo = UtteranceRepository(db_session)
    assert await repo.list_by_session(_u.uuid4()) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/repositories/test_utterances.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'repositories.utterances'`

- [ ] **Step 3: 实现 UtteranceRepository**

Create `backend/src/repositories/utterances.py`:

```python
"""Utterance 仓储：插入与按 session 列出。"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Utterance as UtteranceRow
from models.utterance import Utterance


class UtteranceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def append(self, session_id: uuid.UUID, utt: Utterance) -> int:
        """插入一条 utterance，返回分配的 seq；session_id+seq 唯一约束确保不重号。"""
        next_seq = (
            await self._s.execute(
                select(func.coalesce(func.max(UtteranceRow.seq), 0) + 1).where(
                    UtteranceRow.session_id == session_id
                )
            )
        ).scalar_one()
        row = UtteranceRow(
            id=utt.id,
            session_id=session_id,
            seq=next_seq,
            text=utt.text,
            t_start=utt.t_start,
            t_end=utt.t_end,
            speaker=utt.speaker,
            closed_by=utt.closed_by,
            content_hash=utt.content_hash,
        )
        self._s.add(row)
        await self._s.commit()
        return next_seq

    async def list_by_session(self, session_id: uuid.UUID) -> list[Utterance]:
        stmt = (
            select(UtteranceRow)
            .where(UtteranceRow.session_id == session_id)
            .order_by(UtteranceRow.seq)
        )
        rows = (await self._s.execute(stmt)).scalars().all()
        return [
            Utterance(
                id=r.id, text=r.text, t_start=r.t_start, t_end=r.t_end,
                speaker=r.speaker, closed_by=r.closed_by,
            )
            for r in rows
        ]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/repositories/test_utterances.py -v`
Expected: 3 个测试 PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/src/repositories/utterances.py backend/tests/repositories/test_utterances.py
git commit -m "feat(repo): UtteranceRepository"
```

---

## Task 8: SuggestionRepository

**Files:**
- Create: `backend/src/repositories/suggestions.py`
- Create: `backend/tests/repositories/test_suggestions.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/repositories/test_suggestions.py`:

```python
"""验证 suggestion 仓储：upsert 幂等、按 request_id 更新到 ready。"""
import uuid

import pytest

from models.utterance import Utterance
from repositories.sessions import SessionRepository
from repositories.suggestions import SuggestionRepository
from repositories.utterances import UtteranceRepository


@pytest.mark.asyncio
async def test_upsert_pending_then_ready(db_session):
    """先 upsert pending,再 upsert ready,最终一行,kind/text 已更新——验证幂等键工作。"""
    sid = await SessionRepository(db_session).create()
    await UtteranceRepository(db_session).append(
        sid, Utterance(id="u1", text="t", t_start=0, t_end=0.1, closed_by="vad")
    )
    repo = SuggestionRepository(db_session)
    await repo.upsert_pending(sid, utt_id="u1", request_id="r1", preview_topic="A", preview_rationale="B")
    await repo.upsert_ready(sid, request_id="r1", text="answer")
    items = await repo.list_by_session(sid)
    assert len(items) == 1
    assert items[0]["kind"] == "ready"
    assert items[0]["text"] == "answer"
    assert items[0]["preview_topic"] == "A"


@pytest.mark.asyncio
async def test_upsert_ready_without_pending_creates_row(db_session):
    """没有 pending 直接 ready 也应该插入(短路径场景)——保证 callback 顺序错乱时数据不丢。"""
    sid = await SessionRepository(db_session).create()
    await UtteranceRepository(db_session).append(
        sid, Utterance(id="u1", text="t", t_start=0, t_end=0.1, closed_by="vad")
    )
    repo = SuggestionRepository(db_session)
    await repo.upsert_ready(sid, request_id="r1", text="answer", utt_id="u1")
    items = await repo.list_by_session(sid)
    assert len(items) == 1
    assert items[0]["text"] == "answer"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/repositories/test_suggestions.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 SuggestionRepository**

Create `backend/src/repositories/suggestions.py`:

```python
"""Suggestion 仓储：用 (session_id, request_id) 作为业务幂等键 upsert。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Suggestion


class SuggestionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def upsert_pending(
        self,
        session_id: uuid.UUID,
        *,
        utt_id: str,
        request_id: str,
        preview_topic: str | None,
        preview_rationale: str | None,
    ) -> None:
        row = await self._find(session_id, request_id)
        if row is None:
            self._s.add(Suggestion(
                id=uuid.uuid4(), session_id=session_id, utt_id=utt_id,
                request_id=request_id, kind="pending",
                preview_topic=preview_topic, preview_rationale=preview_rationale,
            ))
        else:
            row.kind = "pending"
            row.preview_topic = preview_topic
            row.preview_rationale = preview_rationale
            row.updated_at = datetime.now(timezone.utc)
        await self._s.commit()

    async def upsert_ready(
        self,
        session_id: uuid.UUID,
        *,
        request_id: str,
        text: str,
        utt_id: str | None = None,
    ) -> None:
        row = await self._find(session_id, request_id)
        if row is None:
            if utt_id is None:
                raise ValueError("upsert_ready without pending requires utt_id")
            self._s.add(Suggestion(
                id=uuid.uuid4(), session_id=session_id, utt_id=utt_id,
                request_id=request_id, kind="ready", text=text,
            ))
        else:
            row.kind = "ready"
            row.text = text
            row.updated_at = datetime.now(timezone.utc)
        await self._s.commit()

    async def _find(self, session_id: uuid.UUID, request_id: str) -> Suggestion | None:
        stmt = select(Suggestion).where(
            Suggestion.session_id == session_id,
            Suggestion.request_id == request_id,
        )
        return (await self._s.execute(stmt)).scalar_one_or_none()

    async def list_by_session(self, session_id: uuid.UUID) -> list[dict]:
        stmt = (
            select(Suggestion)
            .where(Suggestion.session_id == session_id)
            .order_by(Suggestion.created_at)
        )
        rows = (await self._s.execute(stmt)).scalars().all()
        return [
            {
                "id": str(r.id),
                "utt_id": r.utt_id,
                "request_id": r.request_id,
                "kind": r.kind,
                "preview_topic": r.preview_topic,
                "preview_rationale": r.preview_rationale,
                "text": r.text,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/repositories/test_suggestions.py -v`
Expected: 2 个测试 PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/src/repositories/suggestions.py backend/tests/repositories/test_suggestions.py
git commit -m "feat(repo): SuggestionRepository"
```

---

## Task 9: ProfileEntryRepository

**Files:**
- Create: `backend/src/repositories/profile_entries.py`
- Create: `backend/tests/repositories/test_profile_entries.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/repositories/test_profile_entries.py`:

```python
"""验证 profile 仓储：批量插入、按 session 列出（timestamp 升序）。"""
import pytest

from agent.context_store import ProfileEntry
from models.utterance import Utterance
from repositories.profile_entries import ProfileEntryRepository
from repositories.sessions import SessionRepository
from repositories.utterances import UtteranceRepository


@pytest.mark.asyncio
async def test_bulk_insert_and_list_timestamp_order(db_session):
    """批量插入后按 timestamp 升序返回——画像在前端展示时按事实出现顺序排列。"""
    sid = await SessionRepository(db_session).create()
    await UtteranceRepository(db_session).append(
        sid, Utterance(id="u1", text="t", t_start=0, t_end=0.1, closed_by="vad")
    )
    repo = ProfileEntryRepository(db_session)
    await repo.bulk_insert(sid, [
        ProfileEntry(key="职业", value="律师", timestamp=2.0, source_utt_id="u1", subject="本人"),
        ProfileEntry(key="年龄", value="30", timestamp=1.0, source_utt_id="u1", subject="本人"),
    ])
    items = await repo.list_by_session(sid)
    assert [e.key for e in items] == ["年龄", "职业"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/repositories/test_profile_entries.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 ProfileEntryRepository**

Create `backend/src/repositories/profile_entries.py`:

```python
"""ProfileEntry 仓储：批量写入与按 session 列出。"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.context_store import ProfileEntry
from db.models import ProfileEntry as ProfileEntryRow


class ProfileEntryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def bulk_insert(self, session_id: uuid.UUID, entries: list[ProfileEntry]) -> None:
        for e in entries:
            self._s.add(ProfileEntryRow(
                id=uuid.uuid4(),
                session_id=session_id,
                source_utt_id=e.source_utt_id,
                key=e.key,
                value=e.value,
                timestamp=e.timestamp,
                confidence=e.confidence,
                category=e.category,
                subject=e.subject,
            ))
        await self._s.commit()

    async def list_by_session(self, session_id: uuid.UUID) -> list[ProfileEntry]:
        stmt = (
            select(ProfileEntryRow)
            .where(ProfileEntryRow.session_id == session_id)
            .order_by(ProfileEntryRow.timestamp)
        )
        rows = (await self._s.execute(stmt)).scalars().all()
        return [
            ProfileEntry(
                key=r.key, value=r.value, timestamp=r.timestamp,
                source_utt_id=r.source_utt_id or "", confidence=r.confidence,
                category=r.category, subject=r.subject,
            )
            for r in rows
        ]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/repositories/test_profile_entries.py -v`
Expected: 1 个测试 PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/src/repositories/profile_entries.py backend/tests/repositories/test_profile_entries.py
git commit -m "feat(repo): ProfileEntryRepository"
```

---

## Task 10: ContextStore 改造为写穿 DB

**Files:**
- Modify: `backend/src/agent/context_store.py`
- Modify: `backend/tests/agent/test_context_store.py`（若不存在则创建）

**核心改动：**
- 构造签名改为 `ContextStore(session_id, sessionmaker)`——每次写操作内部开短事务，避免长事务把整个 WS 生命周期 hold 住。
- `append_utterance` 同时写 DB + 内存。
- `_profile_worker` 消费队列时同时写 DB。
- 新增 `hydrate()`：启动时把历史 utterance/profile 加载进内存。
- 删除 `to_dict` / `from_dict`（不再有 BLOB 持久化）。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/agent/test_context_store_db.py`:

```python
"""验证 ContextStore 写穿 DB：append/profile worker 都落库，hydrate 能还原内存视图。"""
import pytest

from agent.context_store import ContextStore, ProfileEntry
from db.engine import get_sessionmaker
from models.utterance import Utterance
from repositories.profile_entries import ProfileEntryRepository
from repositories.sessions import SessionRepository
from repositories.utterances import UtteranceRepository


@pytest.mark.asyncio
async def test_append_writes_through_to_db(db_session):
    """append_utterance 后 DB 立即可查到——核心行为：写穿。"""
    sid = await SessionRepository(db_session).create()
    maker = get_sessionmaker(db_session.bind)
    ctx = ContextStore(session_id=sid, sessionmaker=maker)
    await ctx.append_utterance(Utterance(
        id="u1", text="hello", t_start=0.0, t_end=0.5, closed_by="vad",
    ))
    items = await UtteranceRepository(db_session).list_by_session(sid)
    assert len(items) == 1 and items[0].id == "u1"


@pytest.mark.asyncio
async def test_hydrate_loads_existing_utterances(db_session):
    """新建 ContextStore + hydrate 后内存与 DB 一致——刷新 / 进程重启路径。"""
    sid = await SessionRepository(db_session).create()
    await UtteranceRepository(db_session).append(
        sid, Utterance(id="u1", text="hi", t_start=0, t_end=0.1, closed_by="vad")
    )
    await ProfileEntryRepository(db_session).bulk_insert(
        sid, [ProfileEntry(key="k", value="v", timestamp=0.0, source_utt_id="u1", subject="本人")],
    )
    maker = get_sessionmaker(db_session.bind)
    ctx = ContextStore(session_id=sid, sessionmaker=maker)
    await ctx.hydrate()
    assert len(ctx.get_full_history()) == 1
    assert len(ctx.get_profile()) == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/agent/test_context_store_db.py -v`
Expected: FAIL — `ContextStore.__init__() got unexpected keyword argument 'sessionmaker'`

- [ ] **Step 3: 改造 context_store.py**

Open `backend/src/agent/context_store.py`，替换为：

```python
"""ContextStore — 对话上下文与画像的内存视图 + DB 写穿。

设计：
- 读路径：内存 list（避免每条 utterance 来时走 DB）。
- 写路径：内存 + DB 同步写，每次开短事务。
- 启动：调用 hydrate() 从 DB 加载历史。

DB 是真值源；内存只是 cache。重启 / 刷新通过 hydrate 重建。
"""
import asyncio
import contextlib
import logging
import uuid as _uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import async_sessionmaker

from models.utterance import Utterance
from repositories.profile_entries import ProfileEntryRepository
from repositories.utterances import UtteranceRepository

logger = logging.getLogger(__name__)


@dataclass
class ProfileEntry:
    key: str
    value: str
    timestamp: float
    source_utt_id: str
    confidence: float = 1.0
    category: str | None = None
    subject: str = ""


class ContextStore:
    def __init__(
        self,
        *,
        session_id: _uuid.UUID,
        sessionmaker: async_sessionmaker,
    ) -> None:
        self._session_id = session_id
        self._maker = sessionmaker
        self._utterances: list[Utterance] = []
        self._profile: list[ProfileEntry] = []
        self._profile_queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._generation = 0
        self._lock = asyncio.Lock()
        self._shutdown = False

    async def hydrate(self) -> None:
        """从 DB 加载历史 utterances + profile entries 到内存——恢复 cache 视图。"""
        async with self._maker() as s:
            utts = await UtteranceRepository(s).list_by_session(self._session_id)
            profile = await ProfileEntryRepository(s).list_by_session(self._session_id)
        async with self._lock:
            self._utterances = utts
            self._profile = profile
            self._generation = len(utts)

    async def append_utterance(self, utt: Utterance) -> int:
        async with self._maker() as s:
            await UtteranceRepository(s).append(self._session_id, utt)
        async with self._lock:
            self._utterances.append(utt)
            self._generation += 1
            return self._generation

    def get_full_history(self) -> list[Utterance]:
        return list(self._utterances)

    def get_generation(self) -> int:
        return self._generation

    def get_recent_window(self, n: int = 8) -> list[Utterance]:
        if n <= 0:
            return []
        return self._utterances[-n:]

    async def start_profile_worker(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._profile_worker())

    async def enqueue_profile_update(self, utt_id: str, entries: list[ProfileEntry]) -> None:
        await self._profile_queue.put((utt_id, entries))

    def get_profile(self) -> list[ProfileEntry]:
        return sorted(self._profile, key=lambda e: e.timestamp)

    def get_profile_keys(self) -> list[str]:
        sorted_p = sorted(self._profile, key=lambda e: e.timestamp, reverse=True)
        return list(dict.fromkeys(e.key for e in sorted_p))

    def get_profile_summary(self) -> dict[str, dict[str, str]]:
        summary: dict[str, dict[str, str]] = {}
        for entry in self._profile:
            summary.setdefault(entry.subject, {})[entry.key] = entry.value
        return summary

    async def stop_profile_worker(self) -> None:
        self._shutdown = True
        if self._worker_task:
            try:
                await asyncio.wait_for(self._profile_queue.join(), timeout=2.0)
            except TimeoutError:
                pass
            self._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_task
            self._worker_task = None

    async def _profile_worker(self) -> None:
        while not self._shutdown:
            try:
                utt_id, entries = await asyncio.wait_for(self._profile_queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            try:
                async with self._maker() as s:
                    await ProfileEntryRepository(s).bulk_insert(self._session_id, entries)
                self._profile.extend(entries)
            except Exception as exc:
                logger.warning("Profile worker dropped entry: %s", exc)
            self._profile_queue.task_done()
```

**注意：删除 `to_dict` / `from_dict` 方法。**

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/agent/test_context_store_db.py -v`
Expected: PASS。

- [ ] **Step 5: 修复既有 ContextStore 测试**

打开 `backend/tests/agent/test_context_store.py`（若存在），把所有 `ContextStore()` 改为 `ContextStore(session_id=..., utterance_repo=..., profile_repo=...)`。提供 mock repo 即可：

```python
class FakeUttRepo:
    async def append(self, sid, utt): pass
    async def list_by_session(self, sid): return []

class FakeProfileRepo:
    async def bulk_insert(self, sid, entries): pass
    async def list_by_session(self, sid): return []
```

跑全套 agent 测试：

Run: `cd backend && uv run pytest tests/agent/ -v`
Expected: 全部 PASS（或保留少量需在后续 task 修的预期失败，列出来）。

- [ ] **Step 6: 提交**

```bash
git add backend/src/agent/context_store.py backend/tests/agent/
git commit -m "refactor(ctx): ContextStore 写穿 DB,删除 BLOB 序列化"
```

---

## Task 11: SessionManager 重写

**Files:**
- Modify: `backend/src/session/manager.py`
- Modify: `backend/src/session/models.py`
- Delete: `backend/src/session/persistence.py`
- Delete: `backend/src/session/serializer.py`
- Modify: `backend/tests/session/test_manager.py`

**核心改动：**
- 接收 `sessionmaker` 而非 `PersistenceBackend`。
- `create_session` → DB insert；`restore_session` → DB query。
- `update_agent_state` 删除（ContextStore 自己写穿 DB，不需要 Manager 中转）。
- 移除 `_snapshot_loop`、`_snapshot_all`、`_snapshot`（无需快照）。
- TTL 清理改为查 DB。

- [ ] **Step 1: 改写 SessionState**

Open `backend/src/session/models.py`，替换为：

```python
"""Session 运行时状态——只保留进程内需要的字段。

持久化数据全在 Postgres 里。WS 连接状态、live ContextStore/Orchestrator 仅活在内存。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

SessionStatus = Literal["active", "disconnected", "closed"]


@dataclass
class SessionRuntime:
    """单个 session 的进程内 runtime 状态。

    ContextStore 和 Orchestrator 实例在此持有；WS 引用单独由 SessionManager 管理。
    """
    session_id: uuid.UUID
    status: SessionStatus = "active"
    ctx: object | None = None       # ContextStore 实例
    orchestrator: object | None = None
```

- [ ] **Step 2: 写新的 SessionManager 测试**

Open `backend/tests/session/test_manager.py`，替换核心用例为：

```python
"""验证 SessionManager 的 DB 集成：create/restore/close 与 DB 行一致。"""
import uuid

import pytest

from db.engine import create_engine_from_env, get_sessionmaker
from db.base import Base
from db.models import Session as SessionRow
from session.manager import SessionManager


@pytest.fixture
async def manager(db_session):
    """复用 db_session 的 engine,构造 sessionmaker 给 manager。"""
    bind = db_session.bind
    SessionLocal = get_sessionmaker(bind)
    m = SessionManager(SessionLocal, ttl=600.0)
    yield m


@pytest.mark.asyncio
async def test_create_session_persists_in_db(manager, db_session):
    """create 返回的 sid 在 DB 中应该有对应行,status=active。"""
    sid = await manager.create_session()
    row = await db_session.get(SessionRow, sid)
    assert row is not None
    assert row.status == "active"


@pytest.mark.asyncio
async def test_restore_session_returns_disconnected(manager, db_session):
    """已存在的 session,restore 后内存 runtime status=disconnected,等待 WS attach。"""
    sid = await manager.create_session()
    # 模拟进程重启：清空内存
    manager._sessions.clear()
    runtime = await manager.restore_session(sid)
    assert runtime is not None
    assert runtime.status == "disconnected"


@pytest.mark.asyncio
async def test_restore_unknown_returns_none(manager):
    """陌生 sid 返回 None,不抛——main.py 据此决定要不要新建。"""
    assert await manager.restore_session(uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_close_session_marks_closed_in_db(manager, db_session):
    sid = await manager.create_session()
    await manager.close_session(sid)
    row = await db_session.get(SessionRow, sid)
    assert row.status == "closed"
    assert row.closed_at is not None
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/session/test_manager.py -v`
Expected: FAIL —`SessionManager` 现签名不匹配 / `restore_session` 行为差异。

- [ ] **Step 4: 重写 SessionManager**

Open `backend/src/session/manager.py`，整文件替换为：

```python
"""SessionManager — 管理 Session 生命周期 + WS 排他 + TTL 清理。

持久化全交给 Repositories；本类只管 runtime（WS、status 镜像、内存 ctx/orch 引用）。
"""
from __future__ import annotations

import asyncio
import contextlib
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker

from repositories.sessions import SessionRepository
from session.models import SessionRuntime


class SessionManager:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        *,
        ttl: float = 600.0,
        cleanup_interval: float = 60.0,
    ) -> None:
        self._maker = sessionmaker
        self._ttl = ttl
        self._cleanup_interval = cleanup_interval
        self._sessions: dict[uuid.UUID, SessionRuntime] = {}
        self._ws_map: dict[uuid.UUID, object] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task
            self._cleanup_task = None

    async def create_session(self) -> uuid.UUID:
        async with self._maker() as s:
            sid = await SessionRepository(s).create()
        async with self._lock:
            self._sessions[sid] = SessionRuntime(session_id=sid, status="active")
        return sid

    async def restore_session(self, session_id: uuid.UUID) -> SessionRuntime | None:
        async with self._maker() as s:
            row = await SessionRepository(s).get(session_id)
            if row is None:
                return None
        async with self._lock:
            runtime = self._sessions.get(session_id)
            if runtime is None:
                runtime = SessionRuntime(session_id=session_id, status="disconnected")
                self._sessions[session_id] = runtime
            else:
                runtime.status = "disconnected"
        return runtime

    async def get_runtime(self, session_id: uuid.UUID) -> SessionRuntime | None:
        async with self._lock:
            return self._sessions.get(session_id)

    async def attach_ws(self, session_id: uuid.UUID, ws: object) -> object | None:
        async with self._lock:
            old = self._ws_map.pop(session_id, None)
            self._ws_map[session_id] = ws
            runtime = self._sessions.get(session_id)
            if runtime is not None:
                runtime.status = "active"
        async with self._maker() as s:
            await SessionRepository(s).set_status(session_id, "active")
        return old

    async def detach_ws(self, session_id: uuid.UUID, ws: object | None = None) -> None:
        async with self._lock:
            if ws is not None and self._ws_map.get(session_id) is not ws:
                return
            self._ws_map.pop(session_id, None)
            runtime = self._sessions.get(session_id)
            if runtime is not None and runtime.status != "closed":
                runtime.status = "disconnected"
        async with self._maker() as s:
            row = await SessionRepository(s).get(session_id)
            if row is not None and row.status != "closed":
                await SessionRepository(s).set_status(session_id, "disconnected")

    async def close_session(self, session_id: uuid.UUID) -> None:
        async with self._lock:
            runtime = self._sessions.get(session_id)
            if runtime is not None:
                runtime.status = "closed"
            self._ws_map.pop(session_id, None)
        async with self._maker() as s:
            await SessionRepository(s).set_status(session_id, "closed")

    async def set_summary(self, session_id: uuid.UUID, summary: str | None) -> None:
        async with self._maker() as s:
            await SessionRepository(s).set_summary(session_id, summary)

    async def bind_runtime(self, session_id: uuid.UUID, *, ctx, orchestrator) -> None:
        """把 ContextStore / Orchestrator 实例绑到 runtime 上,WS 重连时复用。"""
        async with self._lock:
            runtime = self._sessions.get(session_id)
            if runtime is None:
                return
            runtime.ctx = ctx
            runtime.orchestrator = orchestrator

    async def _cleanup_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
            except asyncio.CancelledError:
                break
            async with self._maker() as s:
                expired = await SessionRepository(s).list_expired_disconnected(self._ttl)
            async with self._lock:
                for sid in expired:
                    self._sessions.pop(sid, None)
                    self._ws_map.pop(sid, None)
```

- [ ] **Step 5: 删除废弃模块**

```bash
rm backend/src/session/persistence.py backend/src/session/serializer.py
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/session/test_manager.py -v`
Expected: PASS。

- [ ] **Step 7: 跑全套测试发现连带破损**

Run: `cd backend && uv run pytest -v --ignore=tests/session/test_integration.py`
Expected: 大部分通过；记录哪些测试还引用了已删除的 `SessionSerializer` / `SQLiteBackend` / `from_dict`，下一 task 处理。

- [ ] **Step 8: 提交**

```bash
git add backend/src/session backend/tests/session/test_manager.py
git rm backend/src/session/persistence.py backend/src/session/serializer.py
git commit -m "refactor(session): SessionManager 切到 DB,移除 BLOB 持久化"
```

---

## Task 12: Orchestrator 与 main.py wiring

**Files:**
- Modify: `backend/src/agent/orchestrator.py`
- Modify: `backend/main.py`

**核心改动：**
- 删除 `Orchestrator.to_dict / from_dict`（不再有 BLOB）；提供 `Orchestrator.fresh(ctx, ...)` 构造器即可。
- `main.py` startup 初始化 DB engine + sessionmaker，传给 SessionManager。
- `legal_session` WS handler：把 ContextStore / Orchestrator 构造改为接收 repos；WS 重连时复用 SessionManager 持有的实例。

- [ ] **Step 1: 改 Orchestrator**

Open `backend/src/agent/orchestrator.py`，删除 `to_dict` 与 `from_dict` 方法（line 361-398 区段）。`PendingRequest` 内部 `to_dict / from_dict` 也一并删除——pending 不再持久化。

确认 `Orchestrator.__init__` 签名不变，仅依赖 ContextStore 实例。

- [ ] **Step 2: 改 main.py startup**

Open `backend/main.py`：

替换 imports（`from session.persistence import SQLiteBackend` → 删除；`from session.serializer import SessionSerializer` → 删除）。新增：

```python
from db.engine import create_engine_from_env, get_sessionmaker  # noqa: E402
from repositories.profile_entries import ProfileEntryRepository  # noqa: E402
from repositories.sessions import SessionRepository  # noqa: E402
from repositories.suggestions import SuggestionRepository  # noqa: E402
from repositories.utterances import UtteranceRepository  # noqa: E402
```

替换 `_startup`：

```python
_engine = None
_sessionmaker = None


@app.on_event("startup")
async def _startup() -> None:
    load_relevance_model()
    global session_manager, _engine, _sessionmaker
    _engine = create_engine_from_env()
    _sessionmaker = get_sessionmaker(_engine)
    session_manager = SessionManager(_sessionmaker, ttl=600.0, cleanup_interval=60.0)
    await session_manager.start()


@app.on_event("shutdown")
async def _shutdown() -> None:
    global session_manager, _engine
    if session_manager is not None:
        await session_manager.stop()
        session_manager = None
    if _engine is not None:
        await _engine.dispose()
        _engine = None
```

- [ ] **Step 3: 改 create_session 端点**

替换 `/api/sessions`：

```python
@app.post("/api/sessions")
async def create_session():
    sid = await session_manager.create_session()
    return {"session_id": str(sid)}
```

注意：`enrollment` 不再传入 SessionManager。律师 enrollment 在 WS handler 里按需 `_session_enrollment()` 重新 deepcopy。

- [ ] **Step 4: 改 WS handler 复用 runtime**

打开 `main.py` 的 `legal_session` 函数。把 ContextStore/Orchestrator 构造段（line 195-208 附近）替换为：

```python
    try:
        import uuid as _uuid
        try:
            sid_uuid = _uuid.UUID(session_id)
        except ValueError:
            await _safe_ws_close(ws, code=1003, reason="invalid session_id")
            return

        runtime = await session_manager.get_runtime(sid_uuid)
        if runtime is None:
            runtime = await session_manager.restore_session(sid_uuid)
        if runtime is None:
            await _safe_ws_close(ws, code=1003, reason="unknown session")
            return

        await session_manager.attach_ws(sid_uuid, ws)

        # 复用已有 ctx/orch 实例（WS 重连场景）；首次连接则新建并 hydrate
        if runtime.ctx is None:
            ctx = ContextStore(session_id=sid_uuid, sessionmaker=_sessionmaker)
            await ctx.hydrate()
            orch = Orchestrator(ctx, session_id=str(sid_uuid), user_id="lawyer-default")
            await session_manager.bind_runtime(sid_uuid, ctx=ctx, orchestrator=orch)
        else:
            ctx = runtime.ctx
            orch = runtime.orchestrator
```

- [ ] **Step 5: 改 suggestion 回调，持久化 suggestion**

打开 `legal_session` 中的 `on_suggestion` 回调（line 210-235），增加 DB 写入：

```python
        async def on_suggestion(text, meta):
            utt_id = meta.get("utt_id")
            request_id = meta.get("request_id")
            try:
                if meta.get("kind") == "pending":
                    if utt_id and request_id:
                        preview = meta.get("preview", {})
                        async with _sessionmaker() as s:
                            await SuggestionRepository(s).upsert_pending(
                                sid_uuid,
                                utt_id=utt_id,
                                request_id=request_id,
                                preview_topic=preview.get("topic"),
                                preview_rationale=preview.get("rationale"),
                            )
                    await ws.send_json({
                        "type": "suggestion.pending",
                        "text": None,
                        "meta": {
                            "utt_id": utt_id,
                            "request_id": request_id,
                            "preview": meta.get("preview", {}),
                        },
                    })
                else:
                    if request_id and text:
                        async with _sessionmaker() as s:
                            await SuggestionRepository(s).upsert_ready(
                                sid_uuid, request_id=request_id, text=text, utt_id=utt_id,
                            )
                    await ws.send_json({
                        "type": "suggestion.ready",
                        "text": text,
                        "meta": {
                            "utt_id": utt_id,
                            **({"request_id": request_id} if request_id else {}),
                        },
                    })
            except (WebSocketDisconnect, RuntimeError):
                pass
            except Exception as exc:
                logger.warning("Suggestion callback failed: %s", exc)
```

- [ ] **Step 6: 移除 update_agent_state 相关调用**

搜索 `update_agent_state` 在 main.py 的使用并删除——ctx 已自己写穿 DB，不需要 Manager 中转 Agent 状态。

```bash
cd backend && grep -n "update_agent_state" main.py src/
```

确认无剩余调用，否则一并清掉。

- [ ] **Step 7: 启动 backend 手测一遍**

```bash
cd backend
docker compose up -d postgres
DATABASE_URL=postgresql+psycopg://legal:legal@localhost:5432/legal_agent uv run alembic upgrade head
DATABASE_URL=postgresql+psycopg://legal:legal@localhost:5432/legal_agent uv run uvicorn main:app --reload
```

另开终端 curl：

```bash
curl -X POST http://localhost:8000/api/sessions
```

Expected: 返回 `{"session_id": "..."}`，Postgres `sessions` 表有新行。

进一步用前端真实跑一段，看 utterance/suggestion 是否落库：

```bash
docker compose exec postgres psql -U legal_agent -c "SELECT id, status FROM sessions;"
docker compose exec postgres psql -U legal_agent -c "SELECT id, text, speaker FROM utterances LIMIT 5;"
docker compose exec postgres psql -U legal_agent -c "SELECT request_id, kind, text FROM suggestions LIMIT 5;"
```

- [ ] **Step 8: 提交**

```bash
git add backend/main.py backend/src/agent/orchestrator.py
git commit -m "feat(wiring): main.py 接入 Postgres,suggestion 持久化,Orchestrator 移除 BLOB"
```

---

## Task 13: GET /api/sessions/{sid}/history endpoint

**Files:**
- Modify: `backend/main.py`
- Create: `backend/tests/api/test_history.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/api/test_history.py`:

```python
"""验证 /api/sessions/{sid}/history 端点：返回 utterance + suggestion 列表，按时序排列。"""
import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from models.utterance import Utterance
from repositories.sessions import SessionRepository
from repositories.suggestions import SuggestionRepository
from repositories.utterances import UtteranceRepository


@pytest.mark.asyncio
async def test_history_returns_empty_for_new_session(db_session):
    """新建 session 立即拉 history,utterances 和 suggestions 都是空数组。"""
    sid = await SessionRepository(db_session).create()
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as ac:
        r = await ac.get(f"/api/sessions/{sid}/history")
    assert r.status_code == 200
    data = r.json()
    assert data["utterances"] == []
    assert data["suggestions"] == []


@pytest.mark.asyncio
async def test_history_returns_data_after_writes(db_session):
    """写入 utterance + suggestion 后,history 能拉到——验证刷新回放路径完整。"""
    sid = await SessionRepository(db_session).create()
    await UtteranceRepository(db_session).append(
        sid, Utterance(id="u1", text="你好", t_start=0, t_end=0.5,
                       speaker="lawyer", closed_by="vad"),
    )
    await SuggestionRepository(db_session).upsert_ready(
        sid, request_id="r1", text="建议", utt_id="u1",
    )
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as ac:
        r = await ac.get(f"/api/sessions/{sid}/history")
    data = r.json()
    assert len(data["utterances"]) == 1
    assert data["utterances"][0]["id"] == "u1"
    assert data["utterances"][0]["text"] == "你好"
    assert len(data["suggestions"]) == 1
    assert data["suggestions"][0]["request_id"] == "r1"
    assert data["suggestions"][0]["text"] == "建议"


@pytest.mark.asyncio
async def test_history_returns_404_for_unknown_session():
    """陌生 session_id 返回 404,而不是空 200——前端据此决定要不要新建会话。"""
    import uuid
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as ac:
        r = await ac.get(f"/api/sessions/{uuid.uuid4()}/history")
    assert r.status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/api/test_history.py -v`
Expected: FAIL — 404 / endpoint 不存在。

- [ ] **Step 3: 实现 endpoint**

打开 `backend/main.py`，在 `/api/sessions` POST 旁边添加：

```python
from fastapi import HTTPException  # 顶部 imports 区，如已存在则跳过


@app.get("/api/sessions/{session_id}/history")
async def get_history(session_id: str):
    import uuid as _u
    try:
        sid = _u.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid session_id")

    async with _sessionmaker() as s:
        row = await SessionRepository(s).get(sid)
        if row is None:
            raise HTTPException(status_code=404, detail="session not found")
        utts = await UtteranceRepository(s).list_by_session(sid)
        sugs = await SuggestionRepository(s).list_by_session(sid)

    return {
        "session_id": str(sid),
        "status": row.status,
        "utterances": [
            {
                "id": u.id, "text": u.text, "t_start": u.t_start,
                "t_end": u.t_end, "speaker": u.speaker, "closed_by": u.closed_by,
            } for u in utts
        ],
        "suggestions": sugs,
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/api/test_history.py -v`
Expected: 3 个测试 PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/main.py backend/tests/api/test_history.py
git commit -m "feat(api): GET /api/sessions/{sid}/history 提供刷新回放数据"
```

---

## Task 14: 前端 history API client + hydration

**Files:**
- Create: `frontend/src/api/sessions.ts`
- Modify: `frontend/src/pages/LiveSession.tsx`

- [ ] **Step 1: 创建 history API client**

Create `frontend/src/api/sessions.ts`:

```typescript
/**
 * Session history API client.
 * 刷新页面后调用 fetchHistory 拉回 transcript + suggestion，再连 WS。
 */
export type HistoryUtterance = {
  id: string;
  text: string;
  t_start: number;
  t_end: number;
  speaker: "lawyer" | "client" | "uncertain" | null;
  closed_by: string;
};

export type HistorySuggestion = {
  id: string;
  utt_id: string;
  request_id: string;
  kind: "pending" | "ready";
  preview_topic: string | null;
  preview_rationale: string | null;
  text: string | null;
  created_at: string;
};

export type SessionHistory = {
  session_id: string;
  status: string;
  utterances: HistoryUtterance[];
  suggestions: HistorySuggestion[];
};

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export async function fetchHistory(sessionId: string): Promise<SessionHistory | null> {
  const r = await fetch(`${API_BASE}/api/sessions/${sessionId}/history`);
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`history fetch failed: ${r.status}`);
  return r.json();
}
```

- [ ] **Step 2: 改 LiveSession 进入时拉 history**

Open `frontend/src/pages/LiveSession.tsx`，在文件顶部 imports 添加：

```typescript
import { fetchHistory } from "@/api/sessions";
```

在 `LiveSession()` 组件内（`useParams` 调用之后），加 hydration effect：

```typescript
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    fetchHistory(sessionId).then((h) => {
      if (cancelled || !h) {
        setHydrated(true);
        return;
      }
      setTranscript(
        h.utterances.map((u) => ({ speaker: u.speaker ?? "uncertain", text: u.text }))
      );
      setSuggestions(
        h.suggestions.map((s): Suggestion => {
          if (s.kind === "pending") {
            return {
              kind: "pending",
              requestId: s.request_id,
              topic: s.preview_topic ?? "",
              rationale: s.preview_rationale ?? "",
            };
          }
          return {
            kind: "ready",
            id: s.id,
            requestId: s.request_id,
            text: s.text ?? "",
            topic: s.preview_topic ?? "",
          };
        })
      );
      setHydrated(true);
    }).catch(() => setHydrated(true));
    return () => {
      cancelled = true;
    };
  }, [sessionId]);
```

只有 `hydrated === true` 之后才允许 WS 连接以避免覆盖历史：把 `useWebSocket(sessionId ?? "", { ... })` 这一行改为：

```typescript
  const { isConnected, error: wsError, sendAudioChunk, confirmIntent, dismissIntent, notifyAudioEnd } =
    useWebSocket(hydrated ? (sessionId ?? "") : "", {
      ...
    });
```

`useWebSocket` 收到空字符串时不连——确认 `frontend/src/hooks/useWebSocket.ts` 有此分支；若无，加：

```typescript
// useWebSocket.ts 开头
if (!sessionId) return;
```

- [ ] **Step 3: suggestion 去 randomUUID 改用 request_id**

在同文件 `onSuggestion` 回调里（line 304-337），把 `id: crypto.randomUUID()` 替换为 `id: rid` 或 `id: \`ready-${rid}\`` 等基于服务端 request_id 的稳定 ID。目的：刷新前后同一条 suggestion 的 React key 保持一致。

具体修改：

```typescript
  const onSuggestion = useCallback((data: SuggestionData) => {
    setSuggestions((prev) => {
      if (data.type === "suggestion.pending") {
        const pending: Suggestion = {
          kind: "pending",
          requestId: data.meta.request_id ?? "",
          topic: data.meta.preview?.topic ?? "",
          rationale: data.meta.preview?.rationale ?? "",
        };
        return [pending, ...prev];
      }
      const rid = data.meta.request_id;
      if (rid) {
        return prev.map((s) => {
          if ((s.kind !== "pending" && s.kind !== "running") || s.requestId !== rid) return s;
          const ready: Suggestion = {
            kind: "ready",
            id: `ready-${rid}`,
            requestId: rid,
            text: data.text ?? "",
            topic: s.topic,
          };
          return ready;
        });
      }
      // 无 request_id 的 ready 不应该再发生(后端总会发 request_id)；保留兜底但用稳定 hash
      const ready: Suggestion = {
        kind: "ready",
        id: `ready-anon-${data.text?.slice(0, 16) ?? "x"}`,
        requestId: "",
        text: data.text ?? "",
        topic: "",
      };
      return [ready, ...prev];
    });
  }, []);
```

- [ ] **Step 4: 手测刷新场景**

```bash
cd backend && docker compose up -d postgres
DATABASE_URL=postgresql+psycopg://legal:legal@localhost:5432/legal_agent uv run uvicorn main:app --reload &

cd ../frontend && pnpm dev
```

1. 打开 LiveSession 页面，说几句话，等待 transcript + suggestion 出现。
2. 浏览器刷新（cmd+R / ctrl+R）。
3. **预期：** 页面 mount 后立刻显示历史 transcript 和 suggestion；WS 续连后新内容继续追加。
4. 检查 Postgres：

```bash
docker compose exec postgres psql -U legal_agent -c "SELECT count(*) FROM utterances;"
```

数字应等于实际说话句数。

- [ ] **Step 5: 前端测试**

Run: `cd frontend && pnpm test`
Expected: 既有测试通过。如有用例针对 LiveSession 的初始状态，可能需要更新以反映 hydration 流程。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/api frontend/src/pages/LiveSession.tsx frontend/src/hooks/useWebSocket.ts
git commit -m "feat(frontend): 刷新后拉 history,suggestion key 用 request_id"
```

---

## Task 15: 清理 + 端到端冒烟

**Files:**
- Modify: `backend/.gitignore`
- Modify: `backend/tests/session/test_integration.py`
- Modify: `README.md`（如有）

- [ ] **Step 1: 删除旧 sessions.db,加 gitignore**

```bash
rm -f backend/data/sessions.db
```

在 `backend/.gitignore`（若无则创建）添加：

```
data/sessions.db
.env
```

- [ ] **Step 2: 修整合测试**

Open `backend/tests/session/test_integration.py`，把所有引用 `SessionSerializer` / `SQLiteBackend` 的地方改为使用新 `sessionmaker` + `SessionManager`。具体改动按编译错误指引修。

跑全套：

Run: `cd backend && uv run pytest -v`
Expected: 全部通过。慢测试如需要：`uv run pytest -m slow -v`。

- [ ] **Step 3: 启动文档更新**

更新 `backend/README.md`（若不存在则在 `CLAUDE.md` 的"构建/运行"部分补一行）：

```
# 启动顺序
1. cd backend && docker compose up -d postgres
2. cp .env.example .env && 填入 DATABASE_URL
3. uv run alembic upgrade head
4. uv run uvicorn main:app --reload
```

- [ ] **Step 4: 端到端冒烟**

按 README 启动整套服务，做以下流程：

1. 前端访问 `http://localhost:5173`，创建新 session。
2. 说话 3-5 句，确认 transcript 与 suggestion 实时出现。
3. **刷新页面**，确认历史全部回放，无重复无丢失。
4. 关闭会话，检查 Postgres 中 `sessions.status='closed'` 且 `summary` 已填充。

- [ ] **Step 5: 提交**

```bash
git add backend/.gitignore backend/tests/session/test_integration.py backend/README.md
git rm backend/data/sessions.db
git commit -m "chore: 清理旧 SQLite 持久化,补启动文档,端到端冒烟通过"
```

---

## 验收清单

完成全部 task 后，逐项手工验证：

- [ ] `docker compose up -d postgres` + `alembic upgrade head` 后，DB 有 5 张表（含 `alembic_version`）
- [ ] POST `/api/sessions` 返回 UUID，`sessions` 表新增一行
- [ ] WS 通话过程中：`utterances` 持续增长，`suggestions` 随 Agent 回答出现
- [ ] 刷新页面：UI 立刻看到历史 transcript + suggestion；WS 续连后新内容继续 append，无重复
- [ ] 关闭会话：`sessions.status='closed'` + `closed_at` 写入 + `summary` 填充
- [ ] 进程重启：内存清空，恢复 session 后历史仍完整可见
- [ ] `uv run pytest` 全套绿
- [ ] `pnpm test` 前端测试绿
- [ ] 旧 `sessions.db` 已删除，`session/persistence.py` 和 `session/serializer.py` 已删除
- [ ] 无遗留对 `update_agent_state` / `SessionSerializer` / `SQLiteBackend` 的引用

---

## 风险与回滚

| 风险 | 应对 |
|---|---|
| Postgres 容器未启动 | startup 立刻报错,显式 `RuntimeError: DATABASE_URL not set` |
| alembic migration 与 ORM 模型漂移 | Task 4 的 fixture 用 `Base.metadata.create_all` 与 migration 并行,任一处漏字段都会暴露 |
| ContextStore 写穿 DB 后并发性能 | 每次 append 都开短事务,Postgres 单实例足够支撑;若需优化用 `INSERT ... ON CONFLICT` batch |
| 前端 hydration 与 WS 顺序竞态 | `hydrated` flag 控制：先拉历史,后连 WS,顺序确定 |
| client_embedding 丢失导致首句 speaker=uncertain | 已知妥协,可接受 |

**回滚路径：** 此 plan 改动是破坏性结构变更,不支持热回滚。如需回退,checkout `main`,删除 Postgres 卷即可。
