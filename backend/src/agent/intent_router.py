"""Intent Router — role-aware intent classification with instructor structured output."""

from typing import Literal

import instructor
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from agent.llm_client import build_qwen_client, QWEN_MODEL


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
        "none",
    ] = Field(description="意图类型")
    law_domain: str | None = Field(
        default=None, description="法律领域，如'劳动法'、'合同法'"
    )
    entities: list[str] = Field(
        default_factory=list, description="关键法律实体，如['竞业限制', 'N+1补偿']"
    )
    rationale: str = Field(description="一句话判断依据，≤50字")


ROLE_AWARE_PROMPT = """\
你正在旁听律师与客户的劳动法律咨询。根据**说话人角色**判断当前这句话的意图。

## 角色判断规则

### 当说话人是 client（客户）：
- ignore: 寒暄、确认、应答（"好的"、"嗯"、"谢谢"）、无法律信息
- simple: 明确的法条查询或金额计算需求。例如："N+1怎么算"、"加班费按什么标准"、"竞业限制最长多久"
- complex: 需要策略判断、风险评估、多步骤综合分析。例如："能赢吗"、"该怎么谈判"、"风险有多大"

### 当说话人是 lawyer（律师）：
- ignore: 常规事实询问（"签合同了吗"、"月薪多少"、"工作多久了"）、流程性引导、确认性应答
- simple: 律师询问某个具体法条或计算，系统可以直接补充。例如：律师问"第47条是什么来着"
- complex: 律师的分析存在明显遗漏或需要补充。例如：律师引用法条但漏了关键补偿标准，或律师给出的建议缺少风险提示

### 当说话人是 uncertain（不确定）：
- 按 client 规则判断

## 意图类型说明
- query_law: 需要引用法条/判例
- compute_compensation: 需要按法律公式计算（赔偿、加班费、年假折算等）
- draft_clause: 需要起草或推荐合同条款
- summarize: 需要归纳当前对话中的事实或诉求
- record_only: 关键信息打点，不主动推送建议
- none: 无具体法律需求

当前说话人: {speaker}
当前句子: {text}
"""


class IntentRouter:
    def __init__(self, client: AsyncOpenAI | None = None, model: str | None = None):
        raw_client = client or build_qwen_client()
        if raw_client is None:
            raise RuntimeError(
                "IntentRouter requires a valid LLM client. "
                "Set DASHSCOPE_API_KEY or pass a client."
            )
        self._client = instructor.from_openai(raw_client, mode=instructor.Mode.MD_JSON)
        self._model = model or QWEN_MODEL

    async def classify(
        self, text: str, speaker: str | None = None
    ) -> IntentResult:
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
