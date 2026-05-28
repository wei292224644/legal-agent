"""IntentRouter — 角色感知的意图分类器。

使用 instructor + Pydantic 结构化输出，根据说话人角色（lawyer/client）
和语义内容判断意图严重程度与类型。
"""

from typing import Literal

import instructor
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from agent.llm_client import build_qwen_client
from agent.prompts import ROLE_AWARE_PROMPT
from config import QWEN_MODEL


class IntentResult(BaseModel):
    """角色感知的意图分类结果"""

    severity: Literal["ignore", "simple", "complex"] = Field(
        description="意图严重程度。ignore=无需响应, simple=可快速回答, complex=需要深度分析"
    )
    intent_type: Literal[
        "query_law",
        "compute_compensation",
        "draft_clause",
        "summarize",
        "record_only",
        "strategy_advice",
        "risk_evaluation",
        "none",
    ] = Field(description="意图类型")
    law_domain: str | None = Field(default=None, description="法律领域，如'劳动法'、'合同法'")
    entities: list[str] = Field(default_factory=list, description="关键法律实体，如['竞业限制', 'N+1补偿']")
    rationale: str = Field(description="一句话判断依据，≤50字")


class IntentRouter:
    """意图路由器：根据说话人角色和文本内容返回结构化分类结果。"""

    def __init__(self, client: AsyncOpenAI | None = None, model: str | None = None):
        """初始化。未提供 client 时自动从环境变量构造千问客户端。"""
        raw_client = client or build_qwen_client()
        if raw_client is None:
            raise RuntimeError("IntentRouter requires a valid LLM client. Set DASHSCOPE_API_KEY or pass a client.")
        self._client = instructor.from_openai(raw_client, mode=instructor.Mode.MD_JSON)
        self._model = model or QWEN_MODEL

    async def classify(self, text: str, speaker: str | None = None) -> IntentResult:
        """对单句发言进行意图分类。

        Args:
            text: 发言原文。
            speaker: 说话人角色（lawyer/client/uncertain/None），None 时按 uncertain 处理。

        Returns:
            结构化意图分类结果，包含严重程度、意图类型、法律领域、实体和判断依据。
        """
        speaker_label = speaker or "uncertain"
        prompt = ROLE_AWARE_PROMPT.format(speaker=speaker_label, text=text)

        result = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=200,
            extra_body={"enable_thinking": False},
            response_model=IntentResult,
        )
        return result
