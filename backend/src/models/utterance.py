"""Utterance 数据模型:一段说话事件。

speaker 4 态(语义两两不同):
- None       — 初始态,声纹尚未算完(异步过程中)
- "lawyer"   — 终态:相似度 ≥ τ_high
- "client"   — 终态:相似度 ≤ τ_low
- "uncertain"— 终态:算完了但拿不准(音频过短或落在双阈值之间)
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Literal

Speaker = Literal["lawyer", "client", "uncertain"]
ClosedBy = Literal["vad", "soft_cap"]


@dataclass
class Utterance:
    id: str
    text: str
    t_start: float
    t_end: float
    speaker: Speaker | None = None
    closed_by: ClosedBy = "vad"
    timestamp: datetime = field(default_factory=datetime.now)
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        self.content_hash = hashlib.sha1(self.text.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict:
        return asdict(self)
