"""HeavyAgent — 基于 Agno 的法律深度分析 Agent。

提供两种分析模式：
- analyze: complex 确认后调用，完整深度分析
- analyze_quick: simple 自动触发，快速回答并做 stale generation 检查
"""

from functools import lru_cache
from pathlib import Path

from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from agno.skills import LocalSkills, Skills
from agno.tools import tool

from agent.context_store import ContextStore
from agent.llm_client import build_deepseek_client
from config import DEEPSEEK_MODEL
from models.utterance import Utterance

_SYSTEM_PROMPT = """你是一名专业的劳动仲裁法律顾问。

你的任务是根据用户提供的对话上下文和用户画像，对法律问题提供深度分析。

当你需要查看用户完整上下文时，请调用 `get_user_context` 工具。

请提供简洁、专业的法律分析，包括：
1. 相关法律法规
2. 计算方式（如涉及金额）
3. 建议行动
"""

_QUICK_SYSTEM_PROMPT = """你是一名专业的劳动仲裁法律顾问。

你的任务是对简单法律查询提供**快速、直接**的回答。只需1-3句话给出答案即可，不需要完整分析。

例如：
- 法条查询 → 直接给出法条编号和内容
- 金额计算 → 直接给出公式和结果
- 模板推荐 → 直接给出模板名称和要点
"""


def _build_model() -> DeepSeek:
    """构造 DeepSeek 模型实例。"""
    client = build_deepseek_client()
    if client is None:
        raise RuntimeError("HeavyAgent requires a valid LLM client. Set DEEPSEEK_API_KEY or pass a model.")
    return DeepSeek(
        id=DEEPSEEK_MODEL,
        api_key=client.api_key,
    )


@lru_cache(maxsize=1)
def _load_skills() -> Skills:
    """加载 skills 目录。缓存避免每次调用都读磁盘。"""
    skills_dir = Path(__file__).parent / "skills"
    return Skills(loaders=[LocalSkills(str(skills_dir))])


class HeavyAgent:
    """法律分析 Agent。每次调用新建实例以隔离状态，skills 读取走缓存。"""

    def __init__(self, ctx: ContextStore, model=None):
        self._ctx = ctx
        self._model = model or _build_model()

    def _make_get_context_tool(self):
        """构造 get_user_context tool，闭包捕获当前 ctx。"""
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

    async def _run_analysis(
        self,
        trigger_utt: Utterance,
        intent_type: str,
        generation: int,
        system_prompt: str,
        check_stale: bool = False,
        with_skills: bool = False,
    ) -> str | None:
        """公共分析逻辑：构造 Agent、调用 LLM、可选 stale 检查。"""
        if check_stale and self._ctx._generation != generation:
            return None

        agent = Agent(
            model=self._model,
            instructions=system_prompt,
            skills=_load_skills() if with_skills else None,
            tools=[self._make_get_context_tool()],
        )
        prompt = f"意图类型: {intent_type}\n\n用户问题: {trigger_utt.text}"
        response = await agent.arun(prompt)

        if check_stale and self._ctx._generation != generation:
            return None

        return getattr(response, "content", None) or str(response)

    async def analyze(self, trigger_utt: Utterance, intent_type: str, generation: int) -> str | None:
        """深度分析（complex 确认后调用），每次新建 Agent 实例，不做 generation 检查。"""
        return await self._run_analysis(
            trigger_utt,
            intent_type,
            generation,
            system_prompt=_SYSTEM_PROMPT,
            with_skills=True,
        )

    async def analyze_quick(self, trigger_utt: Utterance, intent_type: str, generation: int) -> str | None:
        """快速回答（simple 自动触发），带 generation 检查防止 stale。"""
        return await self._run_analysis(
            trigger_utt,
            intent_type,
            generation,
            system_prompt=_QUICK_SYSTEM_PROMPT,
            check_stale=True,
        )
