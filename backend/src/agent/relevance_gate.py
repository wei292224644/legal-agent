"""RelevanceGate — 二分类相关性闸门。

设计:接口只输出 bool,不出 severity、不出 intent_type。当前实现走 Qwen,
后续可无缝换为本地 BERT;调用方契约不变。
"""

from __future__ import annotations

from openai import AsyncOpenAI

from agent.llm_client import build_qwen_client
from agent.prompts import build_relevance_prompt
from config import QWEN_MODEL
from models.utterance import Utterance


class RelevanceGate:
    """单一职责:判断一句话是否需要唤醒 HeavyAgent。"""

    def __init__(self, client: AsyncOpenAI | None = None, model: str | None = None):
        self._client = client or build_qwen_client()
        if self._client is None:
            raise RuntimeError("RelevanceGate requires a valid LLM client. Set DASHSCOPE_API_KEY or pass a client.")
        self._model = model or QWEN_MODEL

    async def is_relevant(self, utt: Utterance) -> bool:
        prompt = build_relevance_prompt(speaker=utt.speaker or "uncertain", text=utt.text)
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=4,
                extra_body={"enable_thinking": False},
            )
            content = (response.choices[0].message.content or "").strip().lower().rstrip(".!,。")
        except Exception:
            # LLM 抖动按 False 处理,不唤醒 HA。画像兜底保证客户事实不丢。
            return False

        if content in ("true", "yes", "是", "需要"):
            return True
        return False
