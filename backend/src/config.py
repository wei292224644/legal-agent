"""集中配置管理。

所有环境变量和可调参数统一在此定义。本模块在导入时自动加载 backend/.env，
因此任何 import config 的代码（含 uvicorn 启动路径）都能拿到 .env 里的值，
无需调用方手动 load_dotenv。已存在的环境变量（shell / CI）优先，不被覆盖。
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# .env 在 backend/ 根目录；本文件位于 backend/src/，向上两级。
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def load_env(path: Path = ENV_PATH) -> None:
    """加载 .env 到 os.environ。override=False：已有环境变量优先。"""
    load_dotenv(path, override=False)


load_env()

# ═══════════════════════════════════════════════════════
# 模型名称
# ═══════════════════════════════════════════════════════
QWEN_MODEL: str = os.getenv("QWEN_MODEL", "qwen3.5-flash")
DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# ═══════════════════════════════════════════════════════
# 千问（DashScope）API 配置
# ═══════════════════════════════════════════════════════
DASHSCOPE_BASE_URL: str = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
LLM_TIMEOUT_QWEN: float = float(os.getenv("LLM_TIMEOUT_QWEN", "5"))

# ═══════════════════════════════════════════════════════
# DeepSeek API 配置
# ═══════════════════════════════════════════════════════
DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
LLM_TIMEOUT_DEEPSEEK: float = float(os.getenv("LLM_TIMEOUT_DEEPSEEK", "8"))

# ═══════════════════════════════════════════════════════
# 音频 / STT 管道配置
# ═══════════════════════════════════════════════════════

# 统一音频采样率（16kHz 为 cam++ / FunASR 训练标准采样率）
SR: int = int(os.getenv("SR", "16000"))

# VAD 判定静默阈值：segment 结束后需观测到至少此长度的静默才认为说话人结束
VAD_SILENCE_MS: int = int(os.getenv("VAD_SILENCE_MS", "400"))

# utterance 软上限：单段连续语音超过此长度后，在微停顿处切分
SOFT_CAP_MS: int = int(os.getenv("SOFT_CAP_MS", "8000"))

# 能量分析帧长（毫秒），用于微停顿检测
FRAME_MS: int = int(os.getenv("FRAME_MS", "30"))

# 微停顿最小长度（毫秒）：连续低能量达到此长度才视为可切分点
MICROPAUSE_MS: int = int(os.getenv("MICROPAUSE_MS", "150"))

# 能量阈值比例：取段内最大能量的此比例作为静音判定线
ENERGY_THRESHOLD_RATIO: float = float(os.getenv("ENERGY_THRESHOLD_RATIO", "0.10"))

# VAD 重检间隔（毫秒），控制流式处理轮询频率
VAD_RECHECK_INTERVAL_MS: int = int(os.getenv("VAD_RECHECK_INTERVAL_MS", "100"))

# ═══════════════════════════════════════════════════════
# Agno HITL / Run 状态持久化
# ═══════════════════════════════════════════════════════

# Agno PostgresDb 连接串。生产推荐;dev 默认连本机 docker postgres。
AGNO_DB_URL: str = os.getenv(
    "AGNO_DB_URL",
    "postgresql+psycopg://legal:legal@localhost:5432/legal_agent",
)

# 单个 child run 的最长在飞时间（秒）。卡死时由 asyncio.wait_for 强制取消。
RUN_TIMEOUT: float = float(os.getenv("RUN_TIMEOUT", "30"))

# 挂起 run 等待律师确认的最长 TTL（秒）。超时由后台扫描 abandon。
PENDING_TTL: float = float(os.getenv("PENDING_TTL", "300"))
