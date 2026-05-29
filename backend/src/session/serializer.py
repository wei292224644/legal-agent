"""Session 序列化器：在 SessionState / dict 与 Agent 对象之间做转换。"""

from __future__ import annotations

from diarization.enrollment import Enrollment
from session.models import SessionState


class SessionSerializer:
    """序列化 / 反序列化工具函数集（无状态）。"""

    @staticmethod
    def to_dict(state: SessionState) -> dict:
        """SessionState → JSON-ready dict。"""
        return {
            "session_id": state.session_id,
            "created_at": state.created_at,
            "last_active_at": state.last_active_at,
            "context_store": state.context_store,
            "orchestrator": state.orchestrator,
            "enrollment": state.enrollment,
            "status": state.status,
            "summary": state.summary,
        }

    @staticmethod
    def from_dict(d: dict) -> SessionState:
        """dict → SessionState。"""
        return SessionState(
            session_id=d["session_id"],
            created_at=d["created_at"],
            last_active_at=d["last_active_at"],
            context_store=d.get("context_store", {}),
            orchestrator=d.get("orchestrator", {}),
            enrollment=d.get("enrollment", {}),
            status=d.get("status", "disconnected"),
            summary=d.get("summary"),
        )

    @staticmethod
    def enrollment_to_dict(enrollment: Enrollment) -> dict:
        """Enrollment → dict（ndarray 已转 list）。"""
        return enrollment.to_dict()

    @staticmethod
    def enrollment_from_dict(d: dict) -> Enrollment:
        """dict → Enrollment。"""
        return Enrollment.from_dict(d)
