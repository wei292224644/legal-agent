"""
Agno Agent implementations for analysis and orchestration.
"""
import os
from typing import Awaitable, Callable

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from agent import AnalysisResult, IntentResult
from audio_pipeline import TranscriptResult

load_dotenv()

AnalyzeFn = Callable[[list[TranscriptResult]], Awaitable[list[IntentResult | AnalysisResult]]]
ExecuteFn = Callable[[IntentResult, list[TranscriptResult]], Awaitable[list[AnalysisResult]]]


class ObserverItem(BaseModel):
    intent: str = Field(default="none", description="simple | complex | none")
    question: str = Field(default="", description="intent card question (complex only)")
    context: str = Field(default="", description="triggering quote")
    category: str = Field(default="", description="statute | contract | risk")
    title: str = Field(default="", description="result title")
    content: str = Field(default="", description="result body")
    citation: str = Field(default="", description="legal citation")
    level: str = Field(default="", description="risk level (risk only)")


class ObserverOutput(BaseModel):
    items: list[ObserverItem] = Field(default_factory=list)


class ExecutorItem(BaseModel):
    category: str = Field(description="statute | contract | risk")
    title: str
    content: str
    citation: str = ""
    level: str = ""


class ExecutorOutput(BaseModel):
    items: list[ExecutorItem] = Field(default_factory=list)


def _build_model() -> OpenAIChat:
    return OpenAIChat(
        id=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        role_map={
            "system": "system",
            "user": "user",
            "assistant": "assistant",
            "tool": "tool",
            "model": "assistant",
        },
    )


ANALYSIS_SYSTEM_PROMPT = """\
你是一位中国执业律师的实时AI助手，正在旁听律师与客户的咨询会谈。

你的任务：
1. 分析客户每一句话，判断是否涉及法律需求
2. 如果涉及法律需求，判断是简单需求（可直接回答）还是复杂需求（需要进一步分析）

简单需求（intent=simple）：
- 可以直接用法条原文回答的问题，例如「某个法条怎么规定的」
- 输出 category/title/content/citation 直接推送给律师

复杂需求（intent=complex）：
- 需要深入分析的问题，例如审查合同、评估风险、出方案
- 输出 question/context 作为意图卡片，由律师确认后再执行

无需求（intent=none）：
- 闲聊、简单应答、不涉及法律的内容

请以 JSON 格式输出。输出格式：{"items": [{...}, {...}]} 包裹的 JSON 数组，每项如下：
- simple: {"intent":"simple","category":"statute","title":"...","content":"...","citation":"...","level":""}
- complex: {"intent":"complex","question":"需要查...吗？","context":"...","category":"","title":"","content":"","citation":"","level":""}
- none: {"intent":"none","question":"","context":"","category":"","title":"","content":"","citation":"","level":""}\
"""

EXECUTOR_SYSTEM_PROMPT = """\
你是一位经验丰富的中国执业律师兼法律顾问。

根据案情摘要和对话上下文，提供以下分析：

1. **法规引用**：精确到条、款、项，只引用中国大陆现行有效的法律法规
2. **合同建议**：提供合同条款建议和范本片段
3. **风险评估**：标注潜在法律风险（高/中/低）

请以 JSON 格式输出。输出格式：{"items": [{...}, {...}]} 包裹的 JSON 数组，每项包含：
category（statute/contract/risk）、title、content、citation、level
level 仅 risk 类需要：高/中/低\
"""


def build_analyze_fn(
    model: OpenAIChat | None = None,
    window_size: int = 10,
) -> AnalyzeFn:
    """Build a real analyze_fn backed by an Agno analysis agent.

    Uses a lightweight prompt and no tools — speed and cancelability over depth.
    """
    agent = Agent(
        name="Legal Analysis Agent",
        model=model or _build_model(),
        description="实时法律需求分析助手",
        instructions=ANALYSIS_SYSTEM_PROMPT,
        system_message_role="system",
        output_schema=ObserverOutput,
        use_json_mode=True,
    )

    async def analyze(context: list[TranscriptResult]) -> list[IntentResult | AnalysisResult]:
        recent = context[-window_size:]
        dialogue = "\n".join(f"{r.speaker}: {r.text}" for r in recent)

        # Batch results from a single run
        results: list[IntentResult | AnalysisResult] = []
        response = await agent.arun(f"对话内容：\n{dialogue}")

        # Agno returns structured output via response.content or direct attribute
        for item in _parse_observer_response(response):
            results.append(item)

        return results

    return analyze


def build_execute_fn(
    model: OpenAIChat | None = None,
) -> ExecuteFn:
    """Build a real execute_fn backed by an Agno orchestration agent.

    Uses full context + tools for deep analysis. Quality over speed.
    """
    agent = Agent(
        name="Legal Orchestration Agent",
        model=model or _build_model(),
        description="法律深度分析执行引擎",
        instructions=EXECUTOR_SYSTEM_PROMPT,
        output_schema=ExecutorOutput,
        use_json_mode=True,
    )

    async def execute(intent: IntentResult, context: list[TranscriptResult]) -> list[AnalysisResult]:
        dialogue = "\n".join(f"{r.speaker}: {r.text}" for r in context)
        prompt = f"""\
案情摘要：
问题：{intent.question}
触发原文：{intent.context}

完整对话：
{dialogue}

请根据以上信息，提供法规引用、合同建议和风险评估。\
"""
        results: list[AnalysisResult] = []
        response = await agent.arun(prompt)

        for item in _parse_executor_response(response):
            results.append(item)

        return results

    return execute


def _parse_observer_response(response) -> list[IntentResult | AnalysisResult]:
    """Parse Agno structured output into domain types."""
    results: list[IntentResult | AnalysisResult] = []

    try:
        import uuid
        content = response.content if hasattr(response, 'content') else response

        if isinstance(content, ObserverOutput):
            items = content.items
        elif isinstance(content, dict):
            items = content.get("items", [content])
        elif isinstance(content, list):
            items = content
        elif isinstance(content, str):
            import json
            parsed = json.loads(content)
            items = parsed.get("items", [parsed]) if isinstance(parsed, dict) else parsed
        else:
            return results
    except Exception:
        return results

    for item in items:
        item_dict = item.model_dump() if isinstance(item, ObserverItem) else item
        if not isinstance(item_dict, dict):
            continue
        intent = item_dict.get("intent", "none")
        if intent == "complex":
            results.append(IntentResult(
                intent_id=str(uuid.uuid4()),
                question=item_dict.get("question", ""),
                context=item_dict.get("context", ""),
            ))
        elif intent == "simple":
            results.append(AnalysisResult(
                category=item_dict.get("category", "statute"),
                title=item_dict.get("title", ""),
                content=item_dict.get("content", ""),
                citation=item_dict.get("citation") or None,
                level=item_dict.get("level") or None,
            ))
        # intent == "none" → skip

    return results


def _parse_executor_response(response) -> list[AnalysisResult]:
    """Parse Agno executor output into AnalysisResult list."""
    results: list[AnalysisResult] = []

    try:
        content = response.content if hasattr(response, 'content') else response

        if isinstance(content, ExecutorOutput):
            items = content.items
        elif isinstance(content, dict):
            items = content.get("items", [content])
        elif isinstance(content, list):
            items = content
        elif isinstance(content, str):
            import json
            parsed = json.loads(content)
            items = parsed.get("items", [parsed]) if isinstance(parsed, dict) else parsed
        else:
            return results
    except Exception:
        return results

    for item in items:
        item_dict = item.model_dump() if isinstance(item, ExecutorItem) else item
        if isinstance(item_dict, dict):
            results.append(AnalysisResult(
                category=item_dict.get("category", ""),
                title=item_dict.get("title", ""),
                content=item_dict.get("content", ""),
                citation=item_dict.get("citation") or None,
                level=item_dict.get("level") or None,
            ))

    return results
