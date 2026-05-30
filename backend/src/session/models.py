"""Session 运行时状态——只保留进程内需要的字段。

持久化数据全在 Postgres 里。WS 连接状态、live ContextStore/Orchestrator 仅活在内存。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

SessionStatus = Literal["active", "disconnected", "closed"]


@dataclass
class SessionRuntime:
    """单个 session 的进程内 runtime 状态。"""
    session_id: uuid.UUID
    status: SessionStatus = "active"
    ctx: object | None = None       # ContextStore 实例
    orchestrator: object | None = None
