"""Profile Agent — qwen3.5-flash legal fact extraction."""
import json
from datetime import datetime

from openai import AsyncOpenAI

from agent.context_store import ProfileEntry
from agent.llm_client import build_qwen_client, QWEN_MODEL
from agent.utils import extract_json_from_markdown


PROFILE_PROMPT = """\
你是一个法律事实提取器，正在旁听律师与客户的咨询会谈。

你的任务是从**当前这句话**中提取所有与法律案件相关的事实信息。
已有的事实（不要重复提取）：
{existing_keys}

提取规则：
1. 只提取**客户陈述的事实**，不提取律师的提问或引导语
2. 如果当前句子是疑问句（包含"吗"、"？"、"多少"、"多久"等），直接输出空数组
3. 如果与已有事实重复，不要输出
4. key 用简洁的中文（如"月薪"、"工龄"、"入职日期"）
5. value 必须是原文中的**具体值**，不能是疑问词或模糊词
6. 如果没有新事实，输出空数组

只输出 JSON，不要任何解释：
{{"entries": [{{"key": "...", "value": "..."}}]}}

当前句子（{speaker}）：{text}
"""


class ProfileAgent:
    def __init__(self, client: AsyncOpenAI | None = None, model: str | None = None):
        self._client = client or build_qwen_client()
        if self._client is None:
            raise RuntimeError("ProfileAgent requires a valid LLM client. Set DASHSCOPE_API_KEY or pass a client.")
        self._model = model or QWEN_MODEL

    async def extract(
        self,
        text: str,
        speaker: str,
        existing_keys: list[str],
        utt_id: str = "",
    ) -> list[ProfileEntry]:
        keys_str = "、".join(existing_keys) if existing_keys else "（无）"
        prompt = PROFILE_PROMPT.format(
            text=text,
            speaker=speaker,
            existing_keys=keys_str,
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
        if not value or len(value.strip()) < 2:
            return False
        stripped = value.strip()
        # Reject pure question phrases
        if stripped in self._QUESTION_WORDS:
            return False
        # Reject values that are mostly question words without numbers
        has_digit = any(c.isdigit() or c in "两二三四五六七八九十百千万亿零" for c in stripped)
        if not has_digit and any(w in stripped for w in ("多少", "多久", "什么")):
            return False
        return True

    def _parse_response(self, content: str, utt_id: str = "") -> list[ProfileEntry]:
        content = extract_json_from_markdown(content)

        try:
            parsed = json.loads(content)
            entries_data = parsed.get("entries", [])
            now = datetime.now()
            entries = []
            for e in entries_data:
                if "key" in e and "value" in e:
                    val = str(e["value"])
                    if not self._is_valid_value(val):
                        continue
                    entries.append(ProfileEntry(
                        key=e["key"],
                        value=val,
                        timestamp=now,
                        source_utt_id=utt_id or "llm",
                        confidence=0.9,
                    ))
            return entries
        except (json.JSONDecodeError, KeyError):
            return []
