"""Tests for RelevanceGate — 二分类相关性闸门。

设计意图：输出只有 bool，不含任何产品策略字段。接入 BERT 后训练目标
不需要随产品迭代变动。
"""

from unittest.mock import patch

import pytest

from agent.relevance_gate import RelevanceGate
from models.utterance import Utterance


def _utt(text: str, speaker: str) -> Utterance:
    return Utterance(id="u_x", text=text, speaker=speaker, t_start=0.0, t_end=1.0)


# ── BERT 推理测试（mock _sync_predict，不依赖真实模型加载）──

@pytest.mark.asyncio
async def test_relevance_true_returns_bool_true():
    gate = RelevanceGate()
    with patch.object(gate, "_sync_predict", return_value=0.9):
        assert await gate.is_relevant(_utt("违法解除赔多少？", "client")) is True


@pytest.mark.asyncio
async def test_relevance_false_returns_bool_false():
    gate = RelevanceGate()
    with patch.object(gate, "_sync_predict", return_value=0.1):
        assert await gate.is_relevant(_utt("律师你好", "client")) is False


@pytest.mark.asyncio
async def test_relevance_threshold_boundary():
    """刚好 0.5 返回 True。"""
    gate = RelevanceGate()
    with patch.object(gate, "_sync_predict", return_value=0.5):
        assert await gate.is_relevant(_utt("某个边界文本", "client")) is True


@pytest.mark.asyncio
async def test_relevance_exception_defaults_false():
    """BERT 推理异常时按 False 处理，和现有 Qwen 抖动行为一致。"""
    gate = RelevanceGate()
    with patch.object(gate, "_sync_predict", side_effect=RuntimeError("mock error")):
        assert await gate.is_relevant(_utt("…", "client")) is False


@pytest.mark.asyncio
async def test_gate_contract_no_severity_no_intent_type():
    """红线契约：gate 的返回值类型是且仅是 bool。"""
    gate = RelevanceGate()
    with patch.object(gate, "_sync_predict", return_value=0.9):
        result = await gate.is_relevant(_utt("劳动法第87条怎么说", "client"))
    assert isinstance(result, bool)
    assert not hasattr(result, "severity")
    assert not hasattr(result, "intent_type")


# ── 模型未加载时的降级行为 ──

@pytest.mark.asyncio
async def test_model_not_loaded_returns_false():
    """模型未加载时 is_relevant 返回 False，不抛异常。"""
    gate = RelevanceGate()
    assert await gate.is_relevant(_utt("任意文本", "client")) is False
