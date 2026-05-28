"""统一 AsyncOpenAI 客户端工厂，支持千问和 DeepSeek。

所有默认值来自 config.py，环境变量名称集中管理，不要在各脚本中重复配置。
"""

import os

from openai import AsyncOpenAI

import config as _cfg

# 向后兼容：重新导出模型名称常量
QWEN_MODEL = _cfg.QWEN_MODEL
DEEPSEEK_MODEL = _cfg.DEEPSEEK_MODEL


def build_qwen_client() -> AsyncOpenAI | None:
    """构造千问（DashScope）异步客户端。未设置 DASHSCOPE_API_KEY 时返回 None。"""
    key = os.getenv("DASHSCOPE_API_KEY")
    if not key:
        return None
    return AsyncOpenAI(
        api_key=key,
        base_url=_cfg.DASHSCOPE_BASE_URL,
        timeout=_cfg.LLM_TIMEOUT_QWEN,
    )


def build_deepseek_client() -> AsyncOpenAI | None:
    """构造 DeepSeek 异步客户端。未设置 DEEPSEEK_API_KEY 时返回 None。"""
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        return None
    return AsyncOpenAI(
        api_key=key,
        base_url=_cfg.DEEPSEEK_BASE_URL,
        timeout=_cfg.LLM_TIMEOUT_DEEPSEEK,
    )
