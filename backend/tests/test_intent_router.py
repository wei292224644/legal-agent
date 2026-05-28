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
async def test_lawyer_citing_statute_is_ignore(mock_ir_client):
    """律师引用法条属于向客户解释，默认 ignore——不再因法律名词触发。"""
    router = mock_ir_client(severity="ignore", intent_type="none")
    result = await router.classify("根据第39条可以解除", speaker="lawyer")
    assert result.severity == "ignore"


@pytest.mark.asyncio
async def test_lawyer_explicit_help_request_triggers_simple(mock_ir_client):
    """律师显式向系统求助（含"系统/AI/帮我"）才触发 simple。"""
    router = mock_ir_client(severity="simple", intent_type="query_law")
    result = await router.classify("系统帮我查一下第47条", speaker="lawyer")
    assert result.severity == "simple"


@pytest.mark.asyncio
async def test_client_quoting_employer_is_record_only(mock_ir_client):
    """客户以"说/公司说"转述对方理由，判 simple/record_only，不要因法律名词升级。"""
    router = mock_ir_client(severity="simple", intent_type="record_only")
    result = await router.classify("说我不胜任工作。", speaker="client")
    assert result.severity == "simple"
    assert result.intent_type == "record_only"


@pytest.mark.asyncio
async def test_client_strategy_question_uses_strategy_advice(mock_ir_client):
    """客户问谈判策略，intent_type 应为 strategy_advice。"""
    router = mock_ir_client(severity="complex", intent_type="strategy_advice")
    result = await router.classify("我该怎么跟公司谈？", speaker="client")
    assert result.severity == "complex"
    assert result.intent_type == "strategy_advice"


@pytest.mark.asyncio
async def test_client_win_rate_question_uses_risk_evaluation(mock_ir_client):
    """客户问胜率，intent_type 应为 risk_evaluation。"""
    router = mock_ir_client(severity="complex", intent_type="risk_evaluation")
    result = await router.classify("能赢吗？", speaker="client")
    assert result.severity == "complex"
    assert result.intent_type == "risk_evaluation"
