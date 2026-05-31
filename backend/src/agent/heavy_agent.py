"""HeavyAgent — Agno child agent 的薄 facade。

只暴露两件事:
- `arun(utt)`: 启动一次 run,返回 Agno RunOutput(含 is_paused/active_requirements)。
- `acontinue_run(run_id, requirements)`: 续跑同一 run,不重头理解。

"是否深析" 完全由 child 自己决定(调不调 gated `deep_analysis` 工具)。
HeavyAgent 不再有 analyze/analyze_quick 两条分支。
"""

from __future__ import annotations

from typing import Any

from agno.agent import Agent
from agno.models.deepseek import DeepSeek

from agent.child_tools import make_deep_analysis_tool, make_fetch_more_transcript_tool
from agent.context_store import ContextStore
from agent.db import get_agno_db
from agent.llm_client import build_deepseek_client
from agent.prompts import build_child_user_prompt, get_child_system_prompt
from config import DEEPSEEK_MODEL
from models.utterance import Utterance

PROFILE_WINDOW_SIZE_FOR_CHILD = 10


def _build_model() -> DeepSeek:
    client = build_deepseek_client()
    if client is None:
        raise RuntimeError("HeavyAgent requires a valid LLM client. Set DEEPSEEK_API_KEY or pass a model.")
    return DeepSeek(id=DEEPSEEK_MODEL, api_key=client.api_key, base_url=str(client.base_url))


class HeavyAgent:
    """child agent facade。Agent 实例在构造期建一次,跨 arun/acontinue_run 复用——
    ctx 是引用语义,child_tools 的闭包不需要"刷新"。"""

    def __init__(
        self,
        ctx: ContextStore,
        session_id: str,
        user_id: str,
        model=None,
    ):
        self._ctx = ctx
        self._session_id = session_id
        self._user_id = user_id
        self._model = model or _build_model()
        self._db = get_agno_db()
        self._agent = Agent(
            model=self._model,
            instructions=get_child_system_prompt(),
            tools=[
                make_deep_analysis_tool(self._ctx),
                make_fetch_more_transcript_tool(self._ctx),
            ],
            db=self._db,
            session_id=self._session_id,
            user_id=self._user_id,
        )

    async def arun(self, trigger_utt: Utterance):
        """启动一次 run。返回 Agno RunOutput(含 is_paused/active_requirements/run_id)。"""
        prompt = build_child_user_prompt(
            trigger_text=trigger_utt.text,
            trigger_speaker=trigger_utt.speaker or "unknown",
            profile_summary=self._ctx.get_profile_summary(),
            recent_window=self._ctx.get_recent_window(PROFILE_WINDOW_SIZE_FOR_CHILD),
        )
        return await self._agent.arun(prompt)

    async def acontinue_run(self, run_id: str, requirements: list[Any] | None = None):
        """续跑同一个 paused run。requirements 由调用方在 confirm 前用 .confirm() 标记好。"""
        return await self._agent.acontinue_run(run_id=run_id, requirements=requirements)
