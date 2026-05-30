"""Tests for RelevanceGate — 二分类相关性闸门。

设计意图:输出只有 bool,不含任何产品策略字段。这样接入 BERT 时训练目标
不需要随产品迭代变动。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.relevance_gate import RelevanceGate
from models.utterance import Utterance


def _utt(text: str, speaker: str) -> Utterance:
    return Utterance(id="u_x", text=text, speaker=speaker, t_start=0.0, t_end=1.0)


def _stub_client(content: str):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=MagicMock(choices=[MagicMock(message=MagicMock(content=content))])
    )
    return client


@pytest.mark.asyncio
async def test_relevance_true_returns_bool_true():
    gate = RelevanceGate(client=_stub_client("true"))
    assert await gate.is_relevant(_utt("违法解除赔多少？", "client")) is True


@pytest.mark.asyncio
async def test_relevance_false_returns_bool_false():
    gate = RelevanceGate(client=_stub_client("false"))
    assert await gate.is_relevant(_utt("律师你好", "client")) is False


@pytest.mark.asyncio
async def test_relevance_strips_punctuation_and_case():
    """Qwen 可能输出 "True." 或 "  YES " 这类噪声,gate 必须归一化。"""
    gate = RelevanceGate(client=_stub_client("True."))
    assert await gate.is_relevant(_utt("竞业限制最长多久", "client")) is True

    gate2 = RelevanceGate(client=_stub_client(" NO "))
    assert await gate2.is_relevant(_utt("好的我懂了", "client")) is False


@pytest.mark.asyncio
async def test_relevance_unparseable_defaults_false():
    """LLM 输出无法解析时按 False 处理:漏判一句的代价(画像兜底捞回)远小于
    误唤醒 HeavyAgent 的成本。"""
    gate = RelevanceGate(client=_stub_client("我不知道"))
    assert await gate.is_relevant(_utt("…", "client")) is False


@pytest.mark.asyncio
async def test_gate_contract_no_severity_no_intent_type():
    """红线契约:gate 的返回值类型是且仅是 bool。新增字段必须不通过 type check。"""
    gate = RelevanceGate(client=_stub_client("true"))
    result = await gate.is_relevant(_utt("劳动法第87条怎么说", "client"))
    assert isinstance(result, bool)
    # 不允许任何属性访问
    assert not hasattr(result, "severity")
    assert not hasattr(result, "intent_type")
