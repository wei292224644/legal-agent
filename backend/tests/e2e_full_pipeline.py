"""全链路实时 E2E:完整音频 1x → STT+声纹 → bus → Orchestrator(IR/PA/HA)。

镜像 main.py 的生产接线,但喂的是录好的完整对话音频而非 WS 实时流。
按真实节奏(1x)模拟现场会谈,同时监控两侧:
  - STT 侧:每段 utterance 的文本/speaker/closed_by/音频区间 + STT 产出延迟
  - bus:有界队列是否丢弃(stt→agent 稳定性的核心信号)
  - agent 侧:IR/PA/HA 每次调用的输入/输出/延迟,以及从 STT 产出到推出建议的反应延迟

运行: cd backend && uv run python tests/e2e_full_pipeline.py
产物:
  tests/runs/<ts>_full_pipeline/events.jsonl    — 统一时间线(STT产出/bus丢弃/建议)
  tests/runs/<ts>_full_pipeline/metrics.json    — STT/bus/反应延迟 摘要
  tests/runs/judgments_full_pipeline_<ts>.jsonl — IR/PA/HA 逐次 IO+延迟
"""

import asyncio
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

# 诊断开关(默认关,生产/常规跑零开销):
#   INSTRUMENT=1 开定向埋点(to_thread 排队/执行 + loop-lag)
#   NO_AGENT=1   跳过 agent 只跑 STT,做 baseline 对比(不花 LLM API)
INSTRUMENT = os.getenv("INSTRUMENT") == "1"
NO_AGENT = os.getenv("NO_AGENT") == "1"
NO_ENROLL = os.getenv("NO_ENROLL") == "1"  # 不传声纹(跳过 cam++),对照 enrollment 延迟
if INSTRUMENT:
    import _instrument

    _instrument.patch_to_thread()

import soundfile as sf  # noqa: E402
from generate_report import analyze_ha, analyze_ir, analyze_pa, load_jsonl  # noqa: E402
from judgment_logger import JudgmentLogger  # noqa: E402
from run_logger import RunLogger  # noqa: E402
from streaming_fixtures import MAIN_WAV, VOICEPRINT_WAV, stream_wav_realtime  # noqa: E402

from agent.bus import UtteranceBus  # noqa: E402
from agent.context_store import ContextStore  # noqa: E402
from agent.heavy_agent import HeavyAgent  # noqa: E402
from agent.intent_router import IntentRouter  # noqa: E402
from agent.orchestrator import Orchestrator  # noqa: E402
from agent.profile_agent import ProfileAgent  # noqa: E402
from diarization.enrollment import enroll_speaker  # noqa: E402
from stt.funasr_stream import stream_stt  # noqa: E402

SPEED = 1.0  # 1x:真实会谈节奏,运行时长 ≈ 音频时长(~7.5min)
DRAIN_GRACE_S = 25.0  # STT 喂完后,等在途 handle_utterance + 后台 quick 分析落定


def _load_enrollment():
    """加载律师声纹注册音频 → enrollment(等价 main.py 的会话级副本)。"""
    audio, sr = sf.read(str(VOICEPRINT_WAV), dtype="float32", always_2d=False)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    return enroll_speaker(audio, sr)


def _stats_ms(values_s: list[float]) -> dict:
    """秒列表 → ms 摘要 (min/avg/p50/p95/max)。"""
    if not values_s:
        return {}
    s = sorted(values_s)

    def pct(p: float) -> float:
        k = (len(s) - 1) * p
        f = int(k)
        c = min(f + 1, len(s) - 1)
        return s[f] if f == c else s[f] + (s[c] - s[f]) * (k - f)

    return {
        "min": round(min(s) * 1000, 1),
        "avg": round(statistics.mean(s) * 1000, 1),
        "p50": round(pct(0.5) * 1000, 1),
        "p95": round(pct(0.95) * 1000, 1),
        "max": round(max(s) * 1000, 1),
    }


async def main():
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    jpath = Path(__file__).parent / "runs" / f"judgments_full_pipeline_{run_id}.jsonl"
    jlogger = JudgmentLogger(
        jpath, session_meta={"script": "e2e_full_pipeline", "wav": MAIN_WAV.name, "speed": SPEED}
    )

    print("=" * 80)
    print(f"全链路实时 E2E — 完整音频 {MAIN_WAV.name} @ {SPEED}x")
    print(f"开始: {datetime.now().strftime('%H:%M:%S')}  | 判断落盘 → {jpath}")
    print("=" * 80, flush=True)

    enrollment = _load_enrollment()

    ctx = ContextStore()
    orch = bus = None
    if not NO_AGENT:
        orch = Orchestrator(
            ctx,
            ir=jlogger.wrap_ir(IntentRouter()),
            pa=jlogger.wrap_pa(ProfileAgent()),
            ha=jlogger.wrap_ha(HeavyAgent(ctx)),
        )
        bus = UtteranceBus(maxsize=10)
        orch.attach_bus(bus)

    # utt_id -> stt 产出时的墙钟,用于算 agent 反应延迟(STT产出 → 推出建议)
    emit_wall: dict[str, float] = {}
    react_latencies: list[float] = []

    with RunLogger("full_pipeline") as rlog:

        async def on_suggestion(text, meta):
            utt_id = meta.get("utt_id", "")
            kind = meta.get("kind", "ready")
            emitted = emit_wall.get(utt_id)
            react_ms = round((time.monotonic() - emitted) * 1000, 1) if emitted else None
            if react_ms is not None:
                react_latencies.append(react_ms / 1000)
            rlog.event(
                f"suggestion.{kind}",
                {
                    "utt_id": utt_id,
                    "severity": meta.get("severity"),
                    "intent_type": meta.get("intent_type"),
                    "react_ms": react_ms,
                    "text_preview": (text or "")[:60].replace("\n", " "),
                },
            )

        if not NO_AGENT:
            orch.set_suggestion_callback(on_suggestion)
            await orch.start()

        probe = _instrument.start_loop_probe() if INSTRUMENT else None

        rlog.event(
            "stream.start",
            {
                "wav": MAIN_WAV.name,
                "speed": SPEED,
                "no_agent": NO_AGENT,
                "instrument": INSTRUMENT,
                "tau_high": enrollment.tau_high,
                "tau_low": enrollment.tau_low,
            },
        )

        stt_latencies: list[float] = []
        raw_speakers: list[str] = []  # orchestrator 会就地改 utt.speaker,必须当下抓
        closed_bys: list[str] = []
        utt_count = 0
        bus_drops = 0

        # 预热 VAD/ASR:这俩在 stream_stt 首次 pull 时才惰性加载(冷启动 5-12s)。
        # 若不预热,stream_start 之后的冷加载会被算进每句 STT 延迟(虚高 ~5s)。
        # cam++ 已由 _load_enrollment 预热。
        import numpy as np

        from stt.funasr_stream import _get_models

        _vad, _asr = _get_models()
        _warm = np.zeros(16000, dtype=np.float32)
        await asyncio.to_thread(_vad.generate, input=_warm)
        await asyncio.to_thread(_asr.generate, input=_warm)

        stream_start = time.monotonic()
        audio = stream_wav_realtime(MAIN_WAV, chunk_ms=100, speed=SPEED)
        async for utt in stream_stt(audio, enrollment=None if NO_ENROLL else enrollment):
            now = time.monotonic()
            stt_lat = now - stream_start - utt.t_end / SPEED  # 音频 t_end 对应墙钟 = start + t_end/speed
            stt_latencies.append(stt_lat)
            raw_speakers.append(utt.speaker or "None")
            closed_bys.append(utt.closed_by)
            emit_wall[utt.id] = now
            utt_count += 1

            rec = utt.to_dict()
            rec["stt_latency_ms"] = round(stt_lat * 1000, 1)
            rlog.event("transcript.final", rec)

            if not NO_AGENT:
                ok = await bus.put(utt)
                if not ok:
                    bus_drops += 1
                    rlog.event("bus.drop", {"utt_id": utt.id, "text_preview": utt.text[:40]})

        rlog.event("stream.end", {"utterance_count": utt_count})

        # drain:先等队列被消费空,再 grace 等最后一句的 IR/PA + 后台 quick 分析落定
        if not NO_AGENT:
            print(f"\n[drain] STT 喂完,等 bus 消费 + 在途 agent 任务(grace {DRAIN_GRACE_S:.0f}s)...", flush=True)
            while bus._q.qsize() > 0:
                await asyncio.sleep(0.5)
            await asyncio.sleep(DRAIN_GRACE_S)

        # ---------- STT / bus / 反应延迟 指标 ----------
        from collections import Counter

        rlog.set_metric("utterance_count", utt_count)
        rlog.set_metric("bus_dropped", bus_drops)
        rlog.set_metric("stt_latency_ms", _stats_ms(stt_latencies))
        rlog.set_metric("react_latency_ms", _stats_ms(react_latencies))
        rlog.set_metric("speaker_dist_raw", dict(Counter(raw_speakers)))
        rlog.set_metric("closed_by_dist", dict(Counter(closed_bys)))
        rlog.set_metric("suggestions_emitted", len(react_latencies))

        if probe is not None:
            probe.cancel()
        if INSTRUMENT:
            _instrument.report(rlog)

        if not NO_AGENT:
            await orch.shutdown()

    jlogger.close()

    print("\n" + "=" * 80)
    print(f"稳定性 & 延迟 摘要  {'[BASELINE: 无 agent]' if NO_AGENT else '[全链路]'}")
    print("=" * 80)
    print(f"\n[STT] utterance={utt_count}  bus_dropped={bus_drops}  (丢弃>0 即 stt→agent 不稳)")
    print(f"  STT 产出延迟(ms): {_stats_ms(stt_latencies)}")
    print(f"  raw speaker 分布: {dict(Counter(raw_speakers))}  (uncertain/None 在 agent 端被降级为 client)")
    print(f"  closed_by 分布:   {dict(Counter(closed_bys))}")

    if os.getenv("STT_TRACE") == "1":
        import stt.funasr_stream as fs

        tl = fs._trace_log
        if tl:
            detect_lag = [r["stable_rel"] - r["audio_end_rel"] for r in tl]  # 段音频结束→进入可产出态
            dt_asr = [r["dt_asr_ms"] / 1000 for r in tl]
            dt_cam = [r["dt_cam_ms"] / 1000 for r in tl]
            yield_total = [r["yield_rel"] - r["audio_end_rel"] for r in tl]  # ≈ 实测 STT 延迟
            buf_minus_e = [(r["buf_ms"] - r["e_ms"]) / 1000 for r in tl]  # 检测到时缓冲超出段尾多少
            print(f"\n[STT-TRACE] n={len(tl)}  enroll={'OFF' if NO_ENROLL else 'ON'}  各阶段拆解(s):")
            print(f"  ① 段检测滞后(音频结束→可产出): {_stats_ms(detect_lag)}")
            print(f"     └ 检测时缓冲超出段尾 buf-e_ms: {_stats_ms(buf_minus_e)}")
            print(f"  ② 等投机ASR dt_asr:            {_stats_ms(dt_asr)}")
            print(f"  ③ cam++ await dt_cam:          {_stats_ms(dt_cam)}")
            print(f"  ④ yield总延迟(①+②+③+握手):     {_stats_ms(yield_total)}")

    if NO_AGENT:
        print(f"\n结束: {datetime.now().strftime('%H:%M:%S')}")
        print("=" * 80, flush=True)
        return

    # ---------- agent 侧分析(复用 generate_report 的分析器读 judgment jsonl) ----------
    records = load_jsonl(jpath)
    ir = analyze_ir(records)
    pa = analyze_pa(records)
    ha = analyze_ha(records)

    print(f"\n[反应延迟] STT产出→推出建议(ms): {_stats_ms(react_latencies)}  (共 {len(react_latencies)} 条建议)")

    print(f"\n[IR] 调用={ir['count']}  延迟(ms) avg={ir['latency']['avg']:.0f} p95={ir['latency']['p95']:.0f} max={ir['latency']['max']:.0f}")
    print(f"  severity 分布: {ir['severity_dist']}")
    print(f"  intent 分布:   {ir['intent_dist']}")

    print(f"\n[PA] 调用={pa['count']}  延迟(ms) avg={pa['latency']['avg']:.0f} p95={pa['latency']['p95']:.0f} max={pa['latency']['max']:.0f}")
    print(f"  提取条目={pa['total_entries']}  空返回率={pa['empty_rate']*100:.0f}%  高频key={dict(list(pa['key_dist'].items())[:8])}")

    print(f"\n[HA] 调用={ha['count']}  事件={ha['event_dist']}")
    print(f"  延迟(ms) avg={ha['latency']['avg']:.0f} p95={ha['latency']['p95']:.0f} max={ha['latency']['max']:.0f}")

    # 一致性校验:每句非律师都应触发 IR;IR 调用数 < utterance 数说明有 utt 在 agent 端失败/丢弃
    print("\n[一致性] IR 调用数应 == utterance 数(每句都过 IR);若小于则有 utt 在 bus 丢弃或 agent 异常")
    print(f"  utterance={utt_count}  IR调用={ir['count']}  差值={utt_count - ir['count']}")

    profile = ctx.get_profile()
    print(f"\n[最终画像] 共 {len(profile)} 条:")
    for e in profile:
        tag = f"[{e.subject}] " if getattr(e, "subject", "") else ""
        print(f"   - {tag}{e.key}: {e.value}")

    print(f"\n结束: {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 80, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
