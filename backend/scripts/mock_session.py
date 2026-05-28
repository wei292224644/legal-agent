"""Mock realtime session for Orchestrator with real API calls.

Features:
1. Simulate a bidirectional lawyer/client dialogue.
2. Insert fixed interval between turns (default 1.5s).
3. Print observation metrics only (no pass/fail judgement).

Usage examples:
    cd backend && uv run python scripts/mock_session.py
    cd backend && uv run python scripts/mock_session.py --turns 10 --interval 1.5
    cd backend && uv run python scripts/mock_session.py --source script --turns 10
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from agno.models.openai import OpenAIChat

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent.context_store import ContextStore, Utterance
from agent.heavy_agent import HeavyAgent
from agent.orchestrator import Orchestrator
from agent.profile_agent import ProfileAgent
from agent.intent_router import IntentRouter

SCRIPT_PATH = (
    Path(__file__).parent.parent / "tests" / "fixtures" / "劳动仲裁对话脚本_角色话版.md"
)
BACKEND_DIR = Path(__file__).parent.parent

SPEAKER_MAP = {
    "客户": "client",
    "律师": "lawyer",
}

DEFAULT_DIALOGUE = [
    ("client", "律师你好，我被公司通知解除劳动合同了。"),
    ("lawyer", "先别急，解除通知是什么时候、什么形式给你的？"),
    ("client", "5月1号口头通知的，没有给书面文件。"),
    ("lawyer", "你的月薪和工龄大概是多少？"),
    ("client", "月薪税前两万五，工龄两年三个月。"),
    ("lawyer", "公司说的解除理由是什么？"),
    ("client", "说我不胜任，但之前没有任何考核和培训记录。"),
    ("lawyer", "你现在最关心是赔偿金额还是是否继续履行合同？"),
    ("client", "我先想知道大概能赔多少。"),
    ("lawyer", "好，我先按违法解除的口径给你算一版。"),
]


@dataclass
class TurnMetric:
    utt_id: str
    speaker: str
    text: str
    generation: int
    handle_ms: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a realtime-like mock dialogue against Orchestrator."
    )
    parser.add_argument(
        "--source",
        choices=["builtin", "script"],
        default="builtin",
        help="Dialogue source: builtin sample or markdown fixture script.",
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=10,
        help="Number of turns to simulate.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.5,
        help="Sleep seconds between turns to mimic realtime speaking gaps.",
    )
    parser.add_argument(
        "--script-path",
        type=Path,
        default=SCRIPT_PATH,
        help="Path to markdown dialogue script when --source=script.",
    )
    parser.add_argument(
        "--show-env",
        action="store_true",
        help="Print whether required API env vars are visible to this process.",
    )
    parser.add_argument(
        "--heavy-provider",
        choices=["deepseek", "qwen"],
        default="deepseek",
        help="Provider used by HeavyAgent. Use qwen when DeepSeek model access is unavailable.",
    )
    parser.add_argument(
        "--heavy-model",
        type=str,
        default=None,
        help="Override heavy model id explicitly.",
    )
    parser.add_argument(
        "--full-suggestion",
        action="store_true",
        help="Print full suggestion text instead of truncated preview.",
    )
    return parser.parse_args()


def load_runtime_env() -> None:
    """Load backend env files for script mode.

    `uv run python ...` does not guarantee auto-loading `.env`, so load explicitly.
    Existing shell env keeps higher priority.
    """
    load_dotenv(BACKEND_DIR / ".env", override=False)
    load_dotenv(BACKEND_DIR / ".env.local", override=False)

load_runtime_env()

def print_env_status() -> None:
    has_qwen = bool(os.getenv("DASHSCOPE_API_KEY"))
    has_deepseek = bool(os.getenv("DEEPSEEK_API_KEY"))
    print(f"[ENV] DASHSCOPE_API_KEY loaded: {has_qwen}")
    print(f"[ENV] DEEPSEEK_API_KEY loaded: {has_deepseek}")


def build_heavy_model(provider: str, model_override: str | None) -> OpenAIChat:
    if provider == "qwen":
        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "heavy-provider=qwen requires DASHSCOPE_API_KEY."
            )
        model_id = model_override or os.getenv("QWEN_MODEL", "qwen3.5-flash")
        base_url = os.getenv(
            "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
    else:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError(
                "heavy-provider=deepseek requires DEEPSEEK_API_KEY."
            )
        model_id = model_override or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    return OpenAIChat(
        id=model_id,
        api_key=api_key,
        base_url=base_url,
        role_map={
            "system": "system",
            "user": "user",
            "assistant": "assistant",
            "tool": "tool",
            "model": "assistant",
        },
    )


def parse_script(path: Path) -> list[tuple[str, str]]:
    """Parse markdown dialogue script into (speaker, text) tuples."""
    results: list[tuple[str, str]] = []
    with path.open("r", encoding="utf-8") as file:
        for raw in file:
            line = raw.strip()
            if not line:
                continue
            match = re.match(r"\*\*(客户|律师)：\*\*\s*(.+)", line)
            if not match:
                continue
            speaker_cn, text = match.groups()
            results.append((SPEAKER_MAP[speaker_cn], text))
    return results


def build_dialogue(source: str, turns: int, script_path: Path) -> list[tuple[str, str]]:
    if source == "script":
        lines = parse_script(script_path)
    else:
        lines = list(DEFAULT_DIALOGUE)

    if turns <= 0:
        raise ValueError("--turns must be > 0")
    if len(lines) < turns:
        raise ValueError(
            f"Dialogue source only has {len(lines)} turns, cannot satisfy --turns={turns}"
        )
    return lines[:turns]


async def run_session(
    dialogue: list[tuple[str, str]],
    interval: float,
    heavy_provider: str,
    heavy_model_override: str | None,
    full_suggestion: bool,
) -> None:
    ctx = ContextStore()
    await ctx.start_profile_worker()
    try:
        ir = IntentRouter()
        pa = ProfileAgent()
        ha = HeavyAgent(ctx, model=build_heavy_model(heavy_provider, heavy_model_override))
        orch = Orchestrator(ctx, ir=ir, pa=pa, ha=ha)
    except RuntimeError as exc:
        await ctx.stop_profile_worker()
        raise RuntimeError(
            "Failed to initialize Orchestrator. "
            "Please set DASHSCOPE_API_KEY and DEEPSEEK_API_KEY in backend/.env "
            "or export them in your shell."
        ) from exc

    turn_metrics: list[TurnMetric] = []
    suggestions: list[tuple[str, dict]] = []

    async def suggestion_callback(text: str, meta: dict):
        suggestions.append((text, meta))
        intent = meta.get("intent", "?")
        preview = text if full_suggestion else text[:70]
        print(f"    [SUGGESTION] intent={intent} | {preview}")

    orch.set_suggestion_callback(suggestion_callback)

    print("\n=== Realtime Mock Session Start ===")
    print(f"Turns: {len(dialogue)}, Interval: {interval:.2f}s")
    print(f"Heavy provider/model: {heavy_provider}/{ha._model.id}")
    print("-" * 60)

    session_t0 = time.perf_counter()

    try:
        for idx, (speaker, text) in enumerate(dialogue, start=1):
            utt_id = f"u_{idx}"
            utterance = Utterance(
                id=utt_id,
                text=text,
                speaker=speaker,
                t_start=0.0,
                t_end=1.0,
                timestamp=datetime.now(),
            )

            turn_t0 = time.perf_counter()
            generation = await orch.handle_utterance(utterance)
            handle_ms = (time.perf_counter() - turn_t0) * 1000

            turn_metrics.append(
                TurnMetric(
                    utt_id=utt_id,
                    speaker=speaker,
                    text=text,
                    generation=generation,
                    handle_ms=handle_ms,
                )
            )

            print(
                f"[TURN {idx:02d}] {speaker:<6} g={generation:<2} "
                f"handle={handle_ms:7.1f}ms | {text}"
            )

            if idx < len(dialogue):
                await asyncio.sleep(interval)

        await ctx._profile_queue.join()
        await asyncio.sleep(0.05)
    finally:
        await ctx.stop_profile_worker()

    elapsed = time.perf_counter() - session_t0
    profile = ctx.get_profile()
    profile_keys = sorted(set(entry.key for entry in profile))

    handle_values = [metric.handle_ms for metric in turn_metrics]
    mean_handle = statistics.mean(handle_values) if handle_values else 0.0
    p95_handle = (
        sorted(handle_values)[int(0.95 * (len(handle_values) - 1))] if handle_values else 0.0
    )

    suggestion_intents: dict[str, int] = {}
    for _, meta in suggestions:
        intent = str(meta.get("intent", "?"))
        suggestion_intents[intent] = suggestion_intents.get(intent, 0) + 1

    print("\n" + "=" * 60)
    print("Observation Metrics")
    print("=" * 60)
    print(f"Total turns           : {len(turn_metrics)}")
    print(f"Total elapsed         : {elapsed:.2f}s")
    print(f"Avg handle latency    : {mean_handle:.1f}ms/turn")
    print(f"P95 handle latency    : {p95_handle:.1f}ms/turn")
    print(f"Suggestion count      : {len(suggestions)}")
    print(f"Suggestion by intent  : {suggestion_intents or '{}'}")
    print(f"Profile entries       : {len(profile)}")
    print(f"Profile keys(unique)  : {profile_keys}")

    if profile:
        print("\nProfile preview:")
        for entry in profile[:20]:
            print(f"  - {entry.key}: {entry.value}")
        if len(profile) > 20:
            print(f"  ... and {len(profile) - 20} more entries")


async def main() -> None:
    args = parse_args()
    if args.show_env:
        print_env_status()
    dialogue = build_dialogue(
        source=args.source,
        turns=args.turns,
        script_path=args.script_path,
    )
    await run_session(
        dialogue=dialogue,
        interval=args.interval,
        heavy_provider=args.heavy_provider,
        heavy_model_override=args.heavy_model,
        full_suggestion=args.full_suggestion,
    )


if __name__ == "__main__":
    asyncio.run(main())
