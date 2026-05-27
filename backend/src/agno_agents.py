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

AnalyzeFn = Callable[
    [dict[str, list[dict]], list[TranscriptResult]],
    Awaitable[tuple[str, list[IntentResult | AnalysisResult]]],
]
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
    facts_summary: str = Field(
        default="",
        description="Updated structured summary of all identified legal facts from the entire conversation",
    )
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

你的任务分为两个阶段：

**阶段1：更新事实摘要**
从对话中提取所有法律相关的事实信息，更新 facts_summary。采用 append-only 方式：
- 每项事实格式：`[时间戳] 事实描述`
- 如果新信息补充/修正了已有事实，追加新条目而非覆盖
- 保留所有历史记录，新条目放在前面
- 事实类型包括但不限于：入职日期、合同签订情况、社保公积金状态、加班情况、年假、
  威胁/胁迫行为、证据持有情况、客户诉求等

**阶段2：判断法律需求**
基于事实摘要和最近对话，判断：
- simple：可直接法条回答的简单问题 → 输出分析卡片
- complex：需要深度分析的问题 → 输出意图卡片（需律师确认）
- none：无法律需求

请以 JSON 格式输出。输出格式：
{
  "facts_summary": "## 关键事实\\n[2024-03-15] 入职日期\\n[未签] 劳动合同未签订\\n...",
  "items": [
    {"intent":"simple","category":"statute","title":"...","content":"...","citation":"...","level":""},
    {"intent":"complex","question":"需要查...吗？","context":"...","category":"","title":"","content":"","citation":"","level":""},
    {"intent":"none","question":"","context":"","category":"","title":"","content":"","citation":"","level":""}
  ]
}\
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
    window_size: int = 15,
) -> AnalyzeFn:
    agent = Agent(
        name="Legal Analysis Agent",
        model=model or _build_model(),
        description="实时法律需求分析助手（事实提取 + 需求判断）",
        instructions=ANALYSIS_SYSTEM_PROMPT,
        system_message_role="system",
        output_schema=ObserverOutput,
        use_json_mode=True,
    )

    async def analyze(
        profile: dict[str, list[dict]],
        context: list[TranscriptResult],
    ) -> tuple[str, list[IntentResult | AnalysisResult]]:
        recent = context[-window_size:]
        dialogue = "\n".join(f"{r.speaker}: {r.text}" for r in recent)

        # Format user profile for the prompt
        profile_text = _format_profile(profile)

        prompt = f"""## 已有事实记录
{profile_text if profile_text else "（无，这是首次分析）"}

## 最近对话
{dialogue}\
"""
        response = await agent.arun(prompt)
        facts_summary, results = _parse_observer_response(response)
        return facts_summary, results

    return analyze


def build_execute_fn(
    model: OpenAIChat | None = None,
) -> ExecuteFn:
    agent = Agent(
        name="Legal Orchestration Agent",
        model=model or _build_model(),
        description="法律深度分析执行引擎",
        instructions=EXECUTOR_SYSTEM_PROMPT,
        system_message_role="system",
        output_schema=ExecutorOutput,
        use_json_mode=True,
    )

    async def execute(intent: IntentResult, context: list[TranscriptResult]) -> list[AnalysisResult]:
        dialogue = "\n".join(f"{r.speaker}: {r.text}" for r in context)
        prompt = f"""## 触发问题
{intent.question}

## 触发原文
{intent.context}

## 完整对话
{dialogue}

请根据以上信息，提供法规引用、合同建议和风险评估。\
"""
        results: list[AnalysisResult] = []
        response = await agent.arun(prompt)

        for item in _parse_executor_response(response):
            results.append(item)

        return results

    return execute


def _format_profile(profile: dict[str, list[dict]]) -> str:
    """Format user profile as readable text for the prompt."""
    if not profile:
        return ""
    lines = []
    for key, records in profile.items():
        for entry in records:
            ts = entry.get("ts", "?")
            val = entry.get("value", "?")
            lines.append(f"[{ts}] {key}: {val}")
    lines.sort()  # chronological
    return "\n".join(lines)


def _parse_observer_response(response) -> tuple[str, list[IntentResult | AnalysisResult]]:
    facts_summary = ""
    results: list[IntentResult | AnalysisResult] = []

    try:
        import uuid
        content = response.content if hasattr(response, 'content') else response

        if isinstance(content, ObserverOutput):
            facts_summary = content.facts_summary or ""
            items = content.items
        elif isinstance(content, dict):
            facts_summary = content.get("facts_summary", "")
            items = content.get("items", [content])
        elif isinstance(content, list):
            items = content
        elif isinstance(content, str):
            import json
            parsed = json.loads(content)
            facts_summary = parsed.get("facts_summary", "") if isinstance(parsed, dict) else ""
            items = parsed.get("items", [parsed]) if isinstance(parsed, dict) else parsed
        else:
            return facts_summary, results
    except Exception:
        return facts_summary, results

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

    return facts_summary, results


def _parse_executor_response(response) -> list[AnalysisResult]:
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
