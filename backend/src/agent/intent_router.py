"""Intent Router — qwen3.5-flash intent classification."""

import json
from dataclasses import dataclass

from openai import AsyncOpenAI

from agent.llm_client import build_qwen_client, QWEN_MODEL
from agent.utils import extract_json_from_markdown


@dataclass
class IntentResult:
    intent: str  # ignore | simple | complex
    rationale: str = ""


INTENT_PROMPT = """\
你是一个意图分类器，正在旁听律师与客户的咨询会谈。

根据**当前这句话**，判断它属于以下哪一类。只判断当前这句话。

分类标准：
- ignore: 日常寒暄、确认、礼貌用语，不含任何法律相关信息。例如："好的"、"谢谢"、"你好"。
- simple: 提出明确的法律需求，可以用单一法条或计算直接回答。例如："赔多少"、"怎么算"、"N+1怎么算"、"加班费按什么标准"。
- complex: 需要综合分析、策略判断、或需要律师确认后才能给出建议。例如："能赢吗"、"该怎么谈"、"风险有多大"、"这份协议能签吗"。

只输出 JSON，不要任何解释：
{{"intent": "ignore|simple|complex", "rationale": "一句话原因 <50字"}}

当前句子：{text}
"""


class IntentRouter:
    def __init__(self, client: AsyncOpenAI | None = None, model: str | None = None):
        self._client = client or build_qwen_client()
        if self._client is None:
            raise RuntimeError("IntentRouter requires a valid LLM client. Set DASHSCOPE_API_KEY or pass a client.")
        self._model = model or QWEN_MODEL

    async def classify(
        self, text: str, context: list[str] | None = None
    ) -> IntentResult:
        prompt = INTENT_PROMPT.format(text=text)

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=50,
            extra_body={"enable_thinking": False},
        )

        content = (response.choices[0].message.content or "").strip()
        return self._parse_response(content)

    @staticmethod
    def _parse_response(content: str) -> IntentResult:
        content = extract_json_from_markdown(content)

        try:
            parsed = json.loads(content)
            intent = parsed.get("intent", "ignore")
            rationale = parsed.get("rationale", "")
            if intent not in ("ignore", "simple", "complex"):
                intent = "ignore"
            return IntentResult(intent=intent, rationale=rationale)
        except (json.JSONDecodeError, KeyError):
            return IntentResult(intent="ignore", rationale="parse error")
