"""Utterance 数据模型：一段说话事件。

speaker 4 态（语义两两不同）：
- None       — 初始态，声纹尚未算完（异步过程中）
- "lawyer"   — 终态：相似度 ≥ τ_high
- "client"   — 终态：相似度 ≤ τ_low
- "uncertain"— 终态：算完了但拿不准（音频过短或落在双阈值之间）
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Literal

Speaker = Literal["lawyer", "client", "uncertain"]
ClosedBy = Literal["vad", "soft_cap"]


@dataclass
class Utterance:
    """单句发言的数据模型。"""

    id: str
    text: str
    t_start: float
    t_end: float
    speaker: Speaker | None = None
    closed_by: ClosedBy = "vad"
    timestamp: float = field(default_factory=time.time)
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        """计算文本哈希用于去重/缓存键。"""
        self.content_hash = hashlib.sha1(self.text.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict:
        """显式字段映射，避免 asdict 深度递归。"""
        return {
            "id": self.id,
            "text": self.text,
            "t_start": self.t_start,
            "t_end": self.t_end,
            "speaker": self.speaker,
            "closed_by": self.closed_by,
            "timestamp": self.timestamp,
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Utterance:
        """从 dict 重建 Utterance。"""
        return cls(
            id=d["id"],
            text=d["text"],
            t_start=d["t_start"],
            t_end=d["t_end"],
            speaker=d.get("speaker"),
            closed_by=d.get("closed_by", "vad"),
            timestamp=d.get("timestamp", 0.0),
        )
