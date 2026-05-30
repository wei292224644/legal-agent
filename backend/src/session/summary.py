"""会谈 AI 摘要生成。

Session 关闭时调用 HeavyAgent 生成结构化摘要。
"""

from __future__ import annotations

import logging
import os

from openai import AsyncOpenAI

from agent.context_store import ContextStore

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "qwen-turbo"
_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


async def generate_summary(ctx: ContextStore) -> str | None:
    """基于完整对话历史和画像生成结构化会谈摘要。

    返回 Markdown 格式的摘要；LLM 调用失败时返回 None。
    """
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        logger.warning("DASHSCOPE_API_KEY not set, skipping summary generation")
        return None

    history = ctx.get_full_history()
    profile = ctx.get_profile()

    lines = ["=== 对话历史 ==="]
    for u in history:
        speaker = u.speaker or "unknown"
        lines.append(f"[{speaker}] {u.text}")

    if profile:
        lines.append("\n=== 已提取画像 ===")
        for e in profile:
            tag = f"[{e.subject}] " if e.subject else ""
            lines.append(f"- {tag}{e.key}: {e.value}")

    transcript = "\n".join(lines)

    prompt = f"""你是一位资深法律助理。请根据以下会谈记录生成一份结构化的会谈摘要。

要求：
1. 用 Markdown 格式输出
2. 包含：案件背景、当事人信息、关键事实、法律问题、下一步建议
3. 客观、准确，不要添加记录中没有的信息
4. 控制在 500 字以内

会谈记录：
{transcript}
"""

    try:
        client = AsyncOpenAI(api_key=api_key, base_url=_BASE_URL)
        response = await client.chat.completions.create(
            model=_DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": "你是一位专业的法律会谈摘要生成助手。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=1024,
        )
        return response.choices[0].message.content
    except Exception as exc:
        logger.warning("Summary generation failed: %s", exc)
        return None
