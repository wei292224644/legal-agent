"""ProfileAgent — 基于 qwen3.5-flash 的法律事实提取器。

从单句发言中提取与案件相关的事实信息（key-value），自动过滤疑问句和重复项。
"""

import json

from openai import AsyncOpenAI

from agent.context_store import ProfileEntry
from agent.llm_client import build_qwen_client
from agent.prompts import build_profile_prompt
from agent.utils import extract_json_from_markdown
from config import QWEN_MODEL


class ProfileAgent:
    """法律事实提取 Agent。"""

    def __init__(self, client: AsyncOpenAI | None = None, model: str | None = None):
        self._client = client or build_qwen_client()
        if self._client is None:
            raise RuntimeError("ProfileAgent requires a valid LLM client. Set DASHSCOPE_API_KEY or pass a client.")
        self._model = model or QWEN_MODEL

    async def extract(
        self,
        text: str,
        speaker: str | None,
        history: list,
        existing_profile: dict[str, str],
        utt_id: str = "",
    ) -> list[ProfileEntry]:
        """从窗口上下文中提取事实条目。

        Args:
            text: 当前发言原文。
            speaker: 说话人角色（lawyer/client/uncertain），None 时按 unknown 处理。
            history: 最近 n 轮对话窗口（list[Utterance]）。
            existing_profile: 已知事实摘要（key → 最新 value）。
            utt_id: 关联的 utterance ID，用于溯源。

        Returns:
            新提取的 ProfileEntry 列表（已过滤疑问词和无效值）。
        """
        speaker_label = speaker or "unknown"
        prompt = build_profile_prompt(
            text=text,
            speaker=speaker_label,
            history=history,
            existing_profile=existing_profile,
        )

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=100,
            extra_body={"enable_thinking": False},
        )

        content = (response.choices[0].message.content or "").strip()
        return self._parse_response(content, utt_id)

    _QUESTION_WORDS = frozenset(("多久", "多少", "什么", "哪里", "谁", "怎么", "怎样", "如何", "吗", "么"))

    def _is_valid_value(self, value: str) -> bool:
        """校验 value 是否为有效事实值（非空、非纯疑问词、含数字优先）。"""
        if not value or len(value.strip()) < 2:
            return False
        stripped = value.strip()
        # Reject pure question phrases
        if stripped in self._QUESTION_WORDS:
            return False
        # Reject values that are mostly question words without numbers
        has_digit = any(c.isdigit() or c in "两二三四五六七八九十百千万亿零" for c in stripped)
        return has_digit or not any(w in stripped for w in ("多少", "多久", "什么"))

    def _parse_response(self, content: str, utt_id: str = "") -> list[ProfileEntry]:
        """解析 LLM 返回的 JSON，提取 ProfileEntry 列表。"""
        content = extract_json_from_markdown(content)

        try:
            parsed = json.loads(content)
            entries_data = parsed.get("entries", [])
            entries = []
            for e in entries_data:
                if isinstance(e, dict) and "key" in e and "value" in e:
                    val = str(e["value"])
                    if not self._is_valid_value(val):
                        continue
                    entries.append(
                        ProfileEntry(
                            key=e["key"],
                            value=val,
                            timestamp=0.0,
                            source_utt_id=utt_id or "llm",
                            confidence=0.9,
                        )
                    )
            return entries
        except (json.JSONDecodeError, KeyError):
            return []
