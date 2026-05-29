"""回归 config.py 从不加载 .env 的 bug。

config.py 被所有 Agent 模块传递性 import，是读取 os.getenv 的中心。
若没人调用 load_dotenv，生产用 `uv run uvicorn main:app` 启动时 .env 不会
被加载，API key 取不到。config.py 应自行加载，不再依赖"调用方负责"。
"""

import os
from pathlib import Path

import config


def test_env_path_points_to_backend_env():
    """ENV_PATH 应指向 backend/.env，防止相对路径被重构悄悄改坏。"""
    assert config.ENV_PATH.name == ".env"
    assert config.ENV_PATH.parent.name == "backend"


def test_load_env_reads_dotenv_into_environment(tmp_path, monkeypatch):
    """load_env 应把 .env 文件里的变量真正注入 os.environ。"""
    env_file = tmp_path / ".env"
    env_file.write_text("LEGAL_AGENT_SENTINEL=loaded_ok\n")
    monkeypatch.delenv("LEGAL_AGENT_SENTINEL", raising=False)

    config.load_env(env_file)

    assert os.getenv("LEGAL_AGENT_SENTINEL") == "loaded_ok"


def test_load_env_does_not_override_existing_env(tmp_path, monkeypatch):
    """已存在的环境变量（shell / CI / pytest）优先于 .env，不被覆盖。"""
    env_file = tmp_path / ".env"
    env_file.write_text("LEGAL_AGENT_SENTINEL=from_dotenv\n")
    monkeypatch.setenv("LEGAL_AGENT_SENTINEL", "from_shell")

    config.load_env(env_file)

    assert os.getenv("LEGAL_AGENT_SENTINEL") == "from_shell"
