"""HeavyAgent child 的两个工具:

- `deep_analysis`: gated。child 调它即触发 HITL pause,等律师确认后续跑。
  入参 (topic, rationale) 是给律师卡片的预览;实际深度分析逻辑在 confirm 后的
  continue_run 里由 LLM 自己推理(本工具不返回真实分析,只承担"暂停信号"语义)。
- `fetch_more_transcript`: 只读。child 默认窗口不够时主动调,拉更早转写切片。
"""

from __future__ import annotations

from agno.tools import tool

from agent.context_store import ContextStore


def make_deep_analysis_tool(ctx: ContextStore):
    """构造 gated 深度分析工具,闭包捕获 ctx。

    Agno 在 child 调用此 tool 时,因 requires_confirmation=True 而暂停 run。
    律师确认后,confirm() + continue_run 让 LLM 继续推理并产出实际深析文本——
    实际"深度分析"是 LLM 在后续推理里完成的,本函数体只在被真正放行后兜底返回一句话。
    """

    @tool(requires_confirmation=True)
    def deep_analysis(topic: str, rationale: str) -> str:
        """启动深度法律分析(需律师确认)。

        Args:
            topic: 这次深析要回答的核心问题,一句话,展示在律师卡片标题。
            rationale: 为什么需要深析(用全画像+全转写)。展示在卡片副标题。
        """
        return f"已就 {topic} 完成深度分析。"

    return deep_analysis


def make_fetch_more_transcript_tool(ctx: ContextStore):
    """构造只读的转写切片拉取工具。"""

    @tool
    def fetch_more_transcript(start_idx: int, end_idx: int) -> str:
        """按索引范围拉取更早/更宽的对话转写。只读,不写画像、不写上下文。

        Args:
            start_idx: 起始索引(包含),负数 clamp 到 0。
            end_idx: 结束索引(不包含),超过总长 clamp 到末尾。
        """
        history = ctx.get_full_history()
        n = len(history)
        s = max(0, start_idx)
        e = min(n, end_idx)
        if s >= e:
            return "(无)"
        lines = [f"[{u.speaker}] {u.text}" for u in history[s:e]]
        return "\n".join(lines)

    return fetch_more_transcript
