"""Unified AsyncOpenAI client factory for Qwen and DeepSeek."""
import os

from openai import AsyncOpenAI

QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen3.5-flash")
# `deepseek-chat` is broadly available; `deepseek-reasoner` may require extra access.
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

def build_qwen_client() -> AsyncOpenAI | None:
    key = os.getenv("DASHSCOPE_API_KEY")
    if not key:
        return None
    return AsyncOpenAI(
        api_key=key,
        base_url=os.getenv(
            "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
        timeout=float(os.getenv("LLM_TIMEOUT_QWEN", "5")),
    )


def build_deepseek_client() -> AsyncOpenAI | None:
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        return None
    return AsyncOpenAI(
        api_key=key,
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        timeout=float(os.getenv("LLM_TIMEOUT_DEEPSEEK", "8")),
    )


