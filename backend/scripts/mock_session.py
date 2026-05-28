"""Mock session — feed dialogue script through Orchestrator.

Usage:
    cd backend && uv run python scripts/mock_session.py
"""
import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent.context_store import ContextStore, Utterance
from agent.orchestrator import Orchestrator


SCRIPT_PATH = Path(__file__).parent.parent / "tests" / "fixtures" / "劳动仲裁对话脚本_角色话版.md"


SPEAKER_MAP = {
    "客户": "client",
    "律师": "lawyer",
}


def parse_script(path: Path) -> list[tuple[str, str]]:
    """Parse markdown dialogue script into (speaker, text) tuples."""
    results = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Match: **客户：** text...  or **律师：** text...
            m = re.match(r"\*\*(客户|律师)：\*\*\s*(.+)", line)
            if m:
                speaker_cn, text = m.groups()
                results.append((SPEAKER_MAP[speaker_cn], text))
    return results


async def main():
    lines = parse_script(SCRIPT_PATH)
    print(f"Loaded {len(lines)} utterances from script\n")

    ctx = ContextStore()
    await ctx.start_profile_worker()
    orch = Orchestrator(ctx)

    hw_count = 0
    async def suggestion_callback(text: str, meta: dict):
        nonlocal hw_count
        hw_count += 1
        intent = meta.get("intent", "?")
        print(f"  [HW #{hw_count}] intent={intent} | text={text[:50]}...")

    orch.set_suggestion_callback(suggestion_callback)

    # Feed utterances
    t0 = datetime.now()
    for i, (speaker, text) in enumerate(lines):
        utt = Utterance(
            id=f"u_{i}",
            text=text,
            speaker=speaker,
            t_start=0.0,
            t_end=1.0,
            timestamp=datetime.now(),
        )
        await orch.handle_utterance(utt)

    # Wait for PA worker to drain
    await ctx._profile_queue.join()
    elapsed = (datetime.now() - t0).total_seconds()

    print(f"\n{'='*60}")
    print(f"Session complete: {len(lines)} utterances in {elapsed:.1f}s")
    print(f"HW triggers: {hw_count}")

    # Print profile summary
    profile = ctx.get_profile()
    print(f"\nProfile ({len(profile)} entries):")
    for e in profile[:20]:
        print(f"  - {e.key}: {e.value}")
    if len(profile) > 20:
        print(f"  ... and {len(profile) - 20} more")


if __name__ == "__main__":
    asyncio.run(main())
