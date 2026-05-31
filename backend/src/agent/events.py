"""WS 出站事件契约。Orchestrator 通过此契约对外说话；main.py 只负责
dump 到 WebSocket，不做任何业务判断。"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class TranscriptDelta(BaseModel):
    type: Literal["transcript"] = "transcript"
    utt_id: str
    speaker: str
    text: str
    t_start: float
    t_end: float
    closed_by: str | None = None
    is_final: bool = True


class InsightReady(BaseModel):
    type: Literal["insight.ready"] = "insight.ready"
    id: str
    utt_id: str
    text: str
    created_at: str


class AnalysisProposed(BaseModel):
    type: Literal["analysis.proposed"] = "analysis.proposed"
    request_id: str
    utt_id: str
    topic: str
    rationale: str
    created_at: str


class AnalysisReady(BaseModel):
    type: Literal["analysis.ready"] = "analysis.ready"
    request_id: str
    utt_id: str
    text: str


class AnalysisDismissed(BaseModel):
    type: Literal["analysis.dismissed"] = "analysis.dismissed"
    request_id: str
    reason: Literal["dismissed", "expired", "abandoned"]


class ProfileEntryPayload(BaseModel):
    key: str
    value: str
    subject: str
    timestamp: float = 0.0
    source_utt_id: str = ""


class ProfileUpdated(BaseModel):
    type: Literal["profile.updated"] = "profile.updated"
    entries: list[ProfileEntryPayload]


class ConfirmAck(BaseModel):
    type: Literal["confirm_ack"] = "confirm_ack"
    request_id: str
    ok: bool


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str


class Pong(BaseModel):
    type: Literal["pong"] = "pong"


OutboundEvent = Annotated[
    TranscriptDelta | InsightReady | AnalysisProposed | AnalysisReady
    | AnalysisDismissed | ProfileUpdated | ConfirmAck | ErrorEvent | Pong,
    Field(discriminator="type"),
]
