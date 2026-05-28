"""Tests for IntentRouter — role-aware classification."""

import pytest


@pytest.fixture
def mock_ir_client():
    """Factory fixture: returns a function that creates stub IntentRouter instances."""
    from agent.intent_router import IntentResult  # noqa: PLC0415

    def _make(**kwargs):
        result = IntentResult(
            severity=kwargs.pop("severity", "ignore"),
            intent_type=kwargs.pop("intent_type", "none"),
            rationale=kwargs.pop("rationale", ""),
            **kwargs,
        )

        class StubIR:
            async def classify(self, text: str, speaker: str | None = None) -> IntentResult:
                return result

        return StubIR()

    return _make


@pytest.mark.asyncio
async def test_classifies_legal_question_as_simple(mock_ir_client):
    router = mock_ir_client(severity="simple", intent_type="query_law")
    result = await router.classify("违法解除赔多少？", speaker="client")
    assert result.severity == "simple"
    assert result.intent_type == "query_law"


@pytest.mark.asyncio
async def test_classifies_greeting_as_ignore(mock_ir_client):
    router = mock_ir_client(severity="ignore", intent_type="none")
    result = await router.classify("律师你好", speaker="client")
    assert result.severity == "ignore"


@pytest.mark.asyncio
async def test_classifies_strategy_question_as_complex(mock_ir_client):
    router = mock_ir_client(severity="complex", intent_type="query_law")
    result = await router.classify("我该怎么跟公司谈？", speaker="client")
    assert result.severity == "complex"


@pytest.mark.asyncio
async def test_lawyer_routine_question_as_ignore(mock_ir_client):
    router = mock_ir_client(severity="ignore", intent_type="none")
    result = await router.classify("你签劳动合同了吗？", speaker="lawyer")
    assert result.severity == "ignore"


@pytest.mark.asyncio
async def test_lawyer_missing_statute_triggers_complex(mock_ir_client):
    router = mock_ir_client(severity="complex", intent_type="query_law")
    result = await router.classify("根据第39条可以解除", speaker="lawyer")
    assert result.severity == "complex"
