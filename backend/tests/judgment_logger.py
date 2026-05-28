"""测试用 — 非侵入式 agent 判断落盘工具（JSONL 格式）。

用途：在 e2e / 稳定性测试里 wrap IR / ProfileAgent / HeavyAgent，
每次调用的输入、输出、延迟落到 tests/runs/judgments_*.jsonl，便于事后审视、
抖动分析、prompt 回归对比。

不动生产代码：通过包装器拦截调用，生产 Orchestrator 不感知。

JSONL 字段：
- ts: ISO 时间戳
- agent: "intent_router" / "profile_agent" / "heavy_agent"
- event: "classify" / "extract" / "analyze_quick" / "analyze"
- latency_ms: 单次调用耗时（ms）
- input: 调用参数（dict）
- output: 返回值（dict / list / str / null）
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


def _serialize(obj: Any) -> Any:
    """把 dataclass / pydantic / Utterance 等递归序列化为 JSON 友好结构。"""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if hasattr(obj, "model_dump"):  # pydantic v2 (IntentResult)
        return obj.model_dump()
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, (list, tuple)):
        return [_serialize(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


class JudgmentLogger:
    """落盘 agent 判断结果到 JSONL。

    用法：
        logger = JudgmentLogger("tests/runs/judgments_xxx.jsonl")
        orch = Orchestrator(
            ctx,
            ir=logger.wrap_ir(IntentRouter()),
            pa=logger.wrap_pa(ProfileAgent()),
            ha=logger.wrap_ha(HeavyAgent(ctx)),
        )
        ...
        logger.close()
    """

    def __init__(self, path: str | Path, session_meta: dict | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("w", buffering=1, encoding="utf-8")
        self._write(
            {
                "event": "session_start",
                "ts": datetime.now().isoformat(),
                "meta": session_meta or {},
            }
        )

    def _write(self, record: dict) -> None:
        self._file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def _log(self, agent: str, event: str, input_: dict, output: Any, latency_ms: float) -> None:
        self._write(
            {
                "ts": datetime.now().isoformat(),
                "agent": agent,
                "event": event,
                "latency_ms": round(latency_ms, 2),
                "input": _serialize(input_),
                "output": _serialize(output),
            }
        )

    def close(self) -> None:
        self._write({"event": "session_end", "ts": datetime.now().isoformat()})
        self._file.close()

    def wrap_ir(self, ir):
        log = self._log

        class _LoggingIR:
            async def classify(self, text, speaker=None):
                t0 = time.monotonic()
                result = await ir.classify(text=text, speaker=speaker)
                log(
                    "intent_router",
                    "classify",
                    {"text": text, "speaker": speaker},
                    result,
                    (time.monotonic() - t0) * 1000,
                )
                return result

        return _LoggingIR()

    def wrap_pa(self, pa):
        log = self._log

        class _LoggingPA:
            async def extract(self, text, speaker, existing_keys, utt_id=""):
                t0 = time.monotonic()
                result = await pa.extract(
                    text=text,
                    speaker=speaker,
                    existing_keys=existing_keys,
                    utt_id=utt_id,
                )
                log(
                    "profile_agent",
                    "extract",
                    {
                        "text": text,
                        "speaker": speaker,
                        "existing_keys": list(existing_keys),
                        "utt_id": utt_id,
                    },
                    result,
                    (time.monotonic() - t0) * 1000,
                )
                return result

        return _LoggingPA()

    def wrap_ha(self, ha):
        log = self._log

        class _LoggingHA:
            async def analyze(self, utt, intent_type, generation):
                t0 = time.monotonic()
                result = await ha.analyze(utt, intent_type, generation)
                log(
                    "heavy_agent",
                    "analyze",
                    {
                        "utt_id": utt.id,
                        "text": utt.text,
                        "speaker": utt.speaker,
                        "intent_type": intent_type,
                        "generation": generation,
                    },
                    result,
                    (time.monotonic() - t0) * 1000,
                )
                return result

            async def analyze_quick(self, utt, intent_type, generation):
                t0 = time.monotonic()
                result = await ha.analyze_quick(utt, intent_type, generation)
                log(
                    "heavy_agent",
                    "analyze_quick",
                    {
                        "utt_id": utt.id,
                        "text": utt.text,
                        "speaker": utt.speaker,
                        "intent_type": intent_type,
                        "generation": generation,
                    },
                    result,
                    (time.monotonic() - t0) * 1000,
                )
                return result

        return _LoggingHA()
