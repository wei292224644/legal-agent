"""WS 出站事件 schema 的 round-trip 与 discriminator 验证。

为什么这样测：每个事件都要能被 model_dump() 序列化后再 model_validate()
还原，且联合类型按 `type` 字段正确分派——这两件事一旦失守，前后端协议立刻
错位。"""
import json
import pytest
from pydantic import TypeAdapter, ValidationError

from agent.events import (
    OutboundEvent,
    TranscriptDelta, InsightReady, AnalysisProposed, AnalysisReady,
    AnalysisDismissed, ProfileUpdated, ProfileEntryPayload,
    ConfirmAck, ErrorEvent, Pong,
)

ADAPTER: TypeAdapter[OutboundEvent] = TypeAdapter(OutboundEvent)


@pytest.mark.parametrize("evt", [
    TranscriptDelta(utt_id="u1", speaker="lawyer", text="hi",
                    t_start=0.0, t_end=1.0, closed_by=None),
    InsightReady(id="ins_1", utt_id="u1", text="结论"),
    AnalysisProposed(request_id="req_1", utt_id="u1",
                     topic="X 是否构成 Y", rationale="因为 Z"),
    AnalysisReady(request_id="req_1", utt_id="u1", text="深度结论"),
    AnalysisDismissed(request_id="req_1", reason="expired"),
    ProfileUpdated(entries=[ProfileEntryPayload(key="姓名", value="张三", subject="client")]),
    ConfirmAck(request_id="req_1", ok=True),
    ErrorEvent(message="oops"),
    Pong(),
])
def test_event_roundtrip_preserves_payload(evt):
    """事件 dump 后能被 union adapter 复原成同型同值。
    这是协议契约最低保证——破了说明 type literal 或字段定义出问题。"""
    raw = json.dumps(evt.model_dump())
    restored = ADAPTER.validate_json(raw)
    assert type(restored) is type(evt)
    assert restored.model_dump() == evt.model_dump()


def test_union_rejects_unknown_type():
    """未知 type 必须 ValidationError，防止 main.py 拿 dict 当 event 用。"""
    with pytest.raises(ValidationError):
        ADAPTER.validate_python({"type": "made_up_event"})


def test_analysis_dismissed_reason_is_constrained():
    """reason 是闭集——拼写错误会被立刻发现，不会变成"未知 dismiss 原因"。"""
    with pytest.raises(ValidationError):
        AnalysisDismissed(request_id="req_1", reason="bogus")  # type: ignore[arg-type]
