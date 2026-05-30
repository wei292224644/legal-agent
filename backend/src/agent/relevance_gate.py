"""RelevanceGate — 二分类相关性闸门。

设计：接口只输出 bool，不出 severity、不出 intent_type。当前实现走本地 BERT，
服务启动时通过 load_relevance_model() 预加载模型。
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import torch
import torch.nn as nn
from transformers import BertModel, BertTokenizer

from models.utterance import Utterance

logger = logging.getLogger(__name__)

# 模型目录：以本文件为基准，向上三级到 backend/，再进 __modles__/
_MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "__modles__" / "intent_router_bert_binary"
_MAX_LEN = 64

_bert_model: BertModel | None = None
_classifier: nn.Linear | None = None
_tokenizer: BertTokenizer | None = None
_device: torch.device | None = None


def load_relevance_model() -> None:
    """加载 BERT 模型到全局变量。失败抛异常，阻止服务启动。"""
    global _bert_model, _classifier, _tokenizer, _device

    if _bert_model is not None:
        return  # 已加载，幂等

    if not _MODEL_DIR.exists():
        raise FileNotFoundError(f"模型目录不存在: {_MODEL_DIR}")

    _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("[RelevanceGate] 加载 BERT 模型 from %s (device=%s)", _MODEL_DIR, _device)

    # 1. Tokenizer
    _tokenizer = BertTokenizer.from_pretrained(str(_MODEL_DIR))

    # 2. BERT encoder
    _bert_model = BertModel.from_pretrained(str(_MODEL_DIR)).to(_device)
    _bert_model.eval()

    # 3. 分类头
    cfg_path = _MODEL_DIR / "config.json"
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    num_classes = cfg.get("num_classes", 2)
    _classifier = nn.Linear(_bert_model.config.hidden_size, num_classes).to(_device)
    _classifier.load_state_dict(
        torch.load(_MODEL_DIR / "classifier.pt", map_location=_device, weights_only=True)
    )
    _classifier.eval()

    logger.info("[RelevanceGate] 模型加载完成")


class RelevanceGate:
    """单一职责：判断一句话是否需要唤醒 HeavyAgent。"""

    def __init__(self, client=None, model=None, threshold: float = 0.5):
        # client / model 参数保留以兼容现有调用（Orchestrator 中 gate or RelevanceGate()），
        # 但不再使用。
        self._threshold = threshold

    async def is_relevant(self, utt: Utterance) -> bool:
        try:
            prob = await asyncio.to_thread(self._sync_predict, utt.text)
        except Exception:
            logger.exception("[RelevanceGate] BERT 推理失败，返回 False")
            return False
        return prob >= self._threshold

    def _sync_predict(self, text: str) -> float:
        """同步推理：返回 should_enter 概率（0~1）。"""
        if _tokenizer is None or _bert_model is None or _classifier is None or _device is None:
            raise RuntimeError("BERT 模型未加载")

        encoding = _tokenizer(
            text,
            max_length=_MAX_LEN,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )
        input_ids = encoding["input_ids"].to(_device)
        attention_mask = encoding["attention_mask"].to(_device)

        with torch.no_grad():
            outputs = _bert_model(input_ids=input_ids, attention_mask=attention_mask)
            pooled = outputs.pooler_output
            logits = _classifier(pooled)
            probs = torch.softmax(logits, dim=1)
            prob_enter = probs[0, 1].item()

        return prob_enter
