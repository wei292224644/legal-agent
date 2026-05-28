"""HeavyAgent — Agno-based legal analysis agent with skills."""

from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.skills import LocalSkills, Skills
from agno.tools import tool

from agent.context_store import ContextStore
from agent.llm_client import build_deepseek_client, DEEPSEEK_MODEL
from models.utterance import Utterance


SYSTEM_PROMPT = """你是一名专业的劳动仲裁法律顾问。

你的任务是根据用户提供的对话上下文和用户画像，对法律问题提供深度分析。

当你需要查看用户完整上下文时，请调用 `get_user_context` 工具。

请提供简洁、专业的法律分析，包括：
1. 相关法律法规
2. 计算方式（如涉及金额）
3. 建议行动
"""

QUICK_SYSTEM_PROMPT = """你是一名专业的劳动仲裁法律顾问。

你的任务是对简单法律查询提供**快速、直接**的回答。只需1-3句话给出答案即可，不需要完整分析。

例如：
- 法条查询 → 直接给出法条编号和内容
- 金额计算 → 直接给出公式和结果
- 模板推荐 → 直接给出模板名称和要点
"""


def _build_model() -> OpenAIChat:
    client = build_deepseek_client()
    if client is None:
        raise RuntimeError(
            "HeavyAgent requires a valid LLM client. "
            "Set DEEPSEEK_API_KEY or pass a model."
        )
    return OpenAIChat(
        id=DEEPSEEK_MODEL,
        api_key=client.api_key,
        base_url=str(client.base_url),
        role_map={
            "system": "system",
            "user": "user",
            "assistant": "assistant",
            "tool": "tool",
            "model": "assistant",
        },
    )


def _load_skills() -> Skills:
    skills_dir = Path(__file__).parent / "skills"
    return Skills(loaders=[LocalSkills(str(skills_dir))])


class HeavyAgent:
    def __init__(self, ctx: ContextStore, model=None):
        self._ctx = ctx
        self._model = model or _build_model()

    def _make_get_context_tool(self):
        ctx = self._ctx

        @tool
        def get_user_context() -> str:
            """读取用户的完整对话历史和画像信息。"""
            profile = ctx.get_profile()
            history = ctx.get_full_history()

            lines = ["=== 用户画像 ==="]
            for e in profile:
                lines.append(f"- {e.key}: {e.value}")

            lines.append("\n=== 对话历史 ===")
            for u in history[-10:]:
                lines.append(f"[{u.speaker}] {u.text}")

            return "\n".join(lines)

        return get_user_context

    async def analyze(
        self, trigger_utt: Utterance, intent_type: str, generation: int
    ) -> str | None:
        """深度分析（complex 确认后调用），每次新建 Agent 实例，不做 generation 检查。"""
        agent = Agent(
            model=self._model,
            instructions=SYSTEM_PROMPT,
            skills=_load_skills(),
            tools=[self._make_get_context_tool()],
        )
        prompt = f"用户问题：{trigger_utt.text}\n意图类型：{intent_type}"
        response = await agent.arun(prompt)
        return response.content if hasattr(response, "content") else str(response)

    async def analyze_quick(
        self, trigger_utt: Utterance, intent_type: str, generation: int
    ) -> str | None:
        """快速回答（simple 自动触发），每次新建 Agent 实例，带 generation 检查防止 stale。"""
        if self._ctx._generation != generation:
            return None

        agent = Agent(
            model=self._model,
            instructions=QUICK_SYSTEM_PROMPT,
            tools=[self._make_get_context_tool()],
        )
        prompt = f"用户问题：{trigger_utt.text}\n意图类型：{intent_type}\n请用1-3句话直接回答。"
        response = await agent.arun(prompt)

        if self._ctx._generation != generation:
            return None

        return response.content if hasattr(response, "content") else str(response)
