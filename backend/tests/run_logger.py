"""测试运行产物记录:实时 stdout + JSONL 事件流 + metrics 摘要。

每次运行落到 tests/runs/<timestamp>/ 下,便于事后回放、对比、诊断。
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path

RUNS_ROOT = Path(__file__).parent / "runs"


class RunLogger:
    """同时落 events.jsonl + 实时 stdout + metrics.json 的小工具。"""

    def __init__(self, label: str):
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.dir = RUNS_ROOT / f"{ts}_{label}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events_fp = (self.dir / "events.jsonl").open("w", encoding="utf-8")
        self.t0 = time.monotonic()
        self.metrics: dict = {}
        print(f"\n[RunLogger] {self.dir}", file=sys.stderr, flush=True)

    def event(self, kind: str, payload: dict | object) -> None:
        if is_dataclass(payload):
            payload = asdict(payload)
        elif not isinstance(payload, dict):
            payload = dict(payload)
        record = {
            "t_wall": round(time.monotonic() - self.t0, 3),
            "kind": kind,
            **payload,
        }
        self.events_fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.events_fp.flush()
        self._print_event(record)

    def _print_event(self, record: dict) -> None:
        t = record["t_wall"]
        kind = record["kind"]
        if kind == "transcript.final":
            sp = record.get("speaker") or "?"
            cb = record.get("closed_by", "?")
            t_start = record.get("t_start", 0.0)
            t_end = record.get("t_end", 0.0)
            text = record.get("text", "")
            print(
                f"[t+{t:6.2f}s] [{cb:>8}] [{sp:>9}] audio[{t_start:6.2f}→{t_end:6.2f}] {text}",
                flush=True,
            )
        else:
            print(f"[t+{t:6.2f}s] {kind}: {record}", flush=True)

    def set_metric(self, key: str, value) -> None:
        self.metrics[key] = value

    def close(self) -> None:
        self.events_fp.close()
        (self.dir / "metrics.json").write_text(
            json.dumps(self.metrics, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[RunLogger] metrics → {self.dir / 'metrics.json'}", file=sys.stderr)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
