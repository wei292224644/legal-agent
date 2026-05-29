"""Session 状态模型。

Session 生命周期：active → disconnected → closed
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

from diarization.enrollment import Enrollment

SessionStatus = Literal["active", "disconnected", "closed"]


@dataclass
class SessionState:
    """Session 运行时状态（纯数据，可序列化）。"""

    session_id: str
    created_at: float = field(default_factory=time.monotonic)
    last_active_at: float = field(default_factory=time.monotonic)
    # Agent 状态 — 由 ContextStore / Orchestrator 的 to_dict() 产出
    context_store: dict = field(default_factory=dict)
    orchestrator: dict = field(default_factory=dict)
    # 声纹注册数据
    enrollment: dict = field(default_factory=dict)
    # 生命周期状态
    status: SessionStatus = "active"
    # AI 摘要（关闭后填充）
    summary: str | None = None

    def touch(self) -> None:
        """更新最后活跃时间。"""
        self.last_active_at = time.monotonic()
