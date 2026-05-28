import pytest

from agent.intent_router import IntentRouter


@pytest.mark.asyncio
async def test_classifies_legal_question_as_simple(mock_llm_client):
    client = mock_llm_client('{"intent": "simple", "rationale": "赔偿计算问题"}')
    router = IntentRouter(client=client)
    result = await router.classify("违法解除赔多少？")
    assert result.intent == "simple"


@pytest.mark.asyncio
async def test_classifies_greeting_as_ignore(mock_llm_client):
    client = mock_llm_client('{"intent": "ignore", "rationale": "问候语"}')
    router = IntentRouter(client=client)
    result = await router.classify("律师你好")
    assert result.intent == "ignore"


@pytest.mark.asyncio
async def test_classifies_strategy_question_as_complex(mock_llm_client):
    client = mock_llm_client('{"intent": "complex", "rationale": "策略问题"}')
    router = IntentRouter(client=client)
    result = await router.classify("我该怎么跟公司谈？")
    assert result.intent == "complex"
