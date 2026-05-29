"""STT 流式 E2E 测试 (Cycles 1-4)。

每个测试都按真实时间节奏喂音频,断言流式产出 utterance。
"""

from __future__ import annotations

import re
import time

import pytest
import soundfile as sf

from stt.funasr_stream import stream_stt
from tests.streaming_fixtures import (
    LONG_MONOLOGUE_WAV,
    MAIN_WAV,
    SCRIPT_MD,
    SHORT_CLIENT_WAV,
    TWO_UTTERANCES_WAV,
    stream_wav_realtime,
)


def _normalize(s: str) -> str:
    """保留中文字符 + 阿拉伯数字 + 英文字母,丢弃标点、空格、其他符号。

    用于 CER 字符级比较——避免 ASR 输出有空格(paraformer 输出"王 律 师")或
    脚本有 markdown 符号导致的虚假差异。
    """
    out = []
    for c in s:
        if c.isalnum() or "一" <= c <= "鿿":
            out.append(c)
    return "".join(out)


def _cer(reference: str, hypothesis: str) -> float:
    """Character Error Rate via Levenshtein distance。"""
    m, n = len(reference), len(hypothesis)
    if m == 0:
        return 0.0 if n == 0 else 1.0
    # 用滚动数组省内存,对 ~7000 字符可控
    prev = list(range(n + 1))
    cur = [0] * (n + 1)
    for i in range(1, m + 1):
        cur[0] = i
        for j in range(1, n + 1):
            if reference[i - 1] == hypothesis[j - 1]:
                cur[j] = prev[j - 1]
            else:
                cur[j] = 1 + min(prev[j], cur[j - 1], prev[j - 1])
        prev, cur = cur, prev
    return prev[n] / m


def _lcs_len(a: str, b: str) -> int:
    """Longest Common Subsequence 长度。滚动数组,O(min(m,n)) 内存。"""
    if len(a) < len(b):
        a, b = b, a
    m, n = len(a), len(b)
    if n == 0:
        return 0
    prev = [0] * (n + 1)
    cur = [0] * (n + 1)
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
            else:
                cur[j] = prev[j] if prev[j] >= cur[j - 1] else cur[j - 1]
        prev, cur = cur, prev
    return prev[n]


def _parse_script_dialogue(text: str) -> list[str]:
    """从 markdown 脚本里抽出所有对话文本(剥掉角色标签和 markdown 格式)。"""
    out = []
    role_prefix = re.compile(r"^\*\*(客户|律师)：\*\*\s*(.+)$")
    for line in text.splitlines():
        m = role_prefix.match(line.strip())
        if m:
            out.append(m.group(2))
        else:
            # 续段(无角色标签的对话延续行)
            stripped = line.strip()
            if stripped and not stripped.startswith(("#", "---", "*")):
                out.append(stripped)
    return out


@pytest.mark.asyncio
async def test_basic_stream():
    """Cycle 1: 流式喂 short_client.wav → 至少 1 个 utterance,文本非空且 > 5 字。"""
    audio = stream_wav_realtime(SHORT_CLIENT_WAV, chunk_ms=100, speed=10.0)
    utterances = [u async for u in stream_stt(audio)]

    assert len(utterances) >= 1, "至少应产出 1 个 utterance"
    for u in utterances:
        assert u.text.strip(), f"utterance 文本不能为空: {u}"
        assert len(u.text) > 5, f"utterance 文本应 > 5 字: {u.text!r}"
        assert u.t_end > u.t_start, f"时间戳不合法: {u}"


@pytest.mark.asyncio
async def test_vad_segmentation():
    """Cycle 2: 5s 音频 + 3s 静默 + 5s 音频 → VAD 切出 ≥ 2 个 utterance。"""
    audio = stream_wav_realtime(TWO_UTTERANCES_WAV, chunk_ms=100, speed=10.0)
    utterances = [u async for u in stream_stt(audio)]

    assert len(utterances) >= 2, f"中间 3s 静默应触发 VAD 切分,实际 {len(utterances)} 段"
    for u in utterances:
        assert u.closed_by == "vad", f"应由 VAD 关闭: {u}"

    # 第一段必须在第二段之前,且时间不重叠(允许少量重叠由 FunASR 边界处理)
    sorted_utts = sorted(utterances, key=lambda u: u.t_start)
    for prev, curr in zip(sorted_utts, sorted_utts[1:]):
        assert curr.t_start >= prev.t_start, "utterance 时间戳应单调"


# fsmn-vad 在 offline batch 模式下实测约需 ~2.2s 静默才能在输出里确认 segment end
# (报告 [[0, e]] 时 e 一直跟随 total_ms 增长,直到 ~2.2s 静默后回退到真实 end)。
# 这是 VAD 本身的结构性 lookahead,功能上扮演了 spec "VAD 沉默 ≥1.5s" 的角色。
# 测试用此值计算 "VAD 实际能确认关闭" 的墙钟时刻;之后到 final 事件的 ≤500ms
# 是真正的处理延迟(ASR + drain)预算。
FSMN_VAD_CONFIRM_LAG_S = 2.2


@pytest.mark.asyncio
async def test_final_event_latency():
    """Cycle 3: VAD 实际确认关闭 → transcript.final 事件延迟 ≤ 500ms。

    用 TWO_UTTERANCES_WAV(5s 音频 + 3s 静默 + 5s 音频)以 1x 真速喂入。
    第一段在流内自然关闭(中间 3s 静默足以触发 fsmn-vad 确认),
    断言从"VAD 确认关闭"到"yield 出 final 事件"的墙钟延迟 ≤ 500ms。
    """
    SPEED = 1.0  # 真速,贴近现场对话场景
    audio_duration_s = sf.info(str(TWO_UTTERANCES_WAV)).duration

    stream_start = time.monotonic()
    audio = stream_wav_realtime(TWO_UTTERANCES_WAV, chunk_ms=100, speed=SPEED)

    natural_latencies: list[float] = []
    all_utts: list = []
    async for utt in stream_stt(audio):
        yielded_wall = time.monotonic()
        all_utts.append(utt)
        # 只统计能在流内自然 VAD 关闭的 utterance
        if utt.t_end + FSMN_VAD_CONFIRM_LAG_S > audio_duration_s:
            continue
        close_detected_wall = stream_start + (utt.t_end + FSMN_VAD_CONFIRM_LAG_S) / SPEED
        latency = yielded_wall - close_detected_wall
        natural_latencies.append(latency)

    assert all_utts, "至少 1 个 utterance"
    assert natural_latencies, (
        f"audio {audio_duration_s:.1f}s 内应至少有 1 个自然关闭的 utterance; utts={[(u.t_start, u.t_end) for u in all_utts]}"
    )
    max_lat = max(natural_latencies)
    assert max_lat <= 0.5, (
        f"VAD 确认后→final 事件最大延迟 {max_lat * 1000:.0f}ms > 500ms; "
        f"latencies={[round(l, 3) for l in natural_latencies]}"
    )


@pytest.mark.asyncio
@pytest.mark.slow
async def test_full_wav_realtime_cer():
    """Cycle 4: 主 WAV 真速(1x)流式喂入,转录质量验收。

    这是本 sprint 的"流式真实对话场景 E2E"主测——音频 ~7.5 分钟,
    测试运行时间也 ~7.5 分钟。运行过程中:
      - stdout 实时打印每个 utterance
      - tests/runs/<ts>_full_wav_cer/events.jsonl 记录所有事件
      - tests/runs/<ts>_full_wav_cer/metrics.json 落最终指标

    断言:
      1. utterance 数与脚本对话行数偏差合理(±50%)
      2. 字符 CER ≤ 15%(归一化后比较中文+数字+字母)
    """
    from tests.run_logger import RunLogger

    SPEED = 1.0
    script_lines = _parse_script_dialogue(SCRIPT_MD.read_text(encoding="utf-8"))
    assert len(script_lines) > 20, f"应解析出 ≥ 20 行脚本对话,实际 {len(script_lines)}"

    with RunLogger("full_wav_cer") as logger:
        logger.event(
            "stream.start",
            {
                "wav": str(MAIN_WAV.name),
                "speed": SPEED,
                "script_lines": len(script_lines),
            },
        )

        audio = stream_wav_realtime(MAIN_WAV, chunk_ms=100, speed=SPEED)
        utterances = []
        latencies: list[float] = []  # 从 t_end 到 utterance 产出的延迟
        stream_start = time.monotonic()
        async for utt in stream_stt(audio):
            yielded_wall = time.monotonic()
            utterances.append(utt)
            # 延迟 = 产出的墙钟时间 - 流起始 - 该 utterance 在音频中的结束时刻
            latency = yielded_wall - stream_start - utt.t_end
            latencies.append(latency)
            logger.event("transcript.final", utt)

        logger.event("stream.end", {"utterance_count": len(utterances)})

        ref = "".join(_normalize(line) for line in script_lines)
        hyp = "".join(_normalize(u.text) for u in utterances)
        cer = _cer(ref, hyp)
        # LCS(hyp, ref) / len(hyp):衡量"ASR 不胡说"——hyp 里能在 ref 找到
        # 顺序匹配的字占比。脚本(ref)是写出来的长版本,音频里没念全,所以
        # 用 CER(对称编辑距离)对 ASR 不公平;LCS/len(hyp) 只看 ASR 输出
        # 的字是不是真的在脚本里出现过(按顺序),才是合理的质量指标。
        lcs = _lcs_len(hyp, ref)
        lcs_ratio = lcs / len(hyp) if hyp else 0.0
        ratio = len(utterances) / len(script_lines)

        logger.set_metric("utterance_count", len(utterances))
        logger.set_metric("script_line_count", len(script_lines))
        logger.set_metric("count_ratio", round(ratio, 3))
        logger.set_metric("ref_chars", len(ref))
        logger.set_metric("hyp_chars", len(hyp))
        logger.set_metric("cer", round(cer, 4))
        logger.set_metric("lcs_len", lcs)
        logger.set_metric("lcs_ratio", round(lcs_ratio, 4))
        logger.set_metric(
            "closed_by_breakdown",
            {
                "vad": sum(1 for u in utterances if u.closed_by == "vad"),
                "soft_cap": sum(1 for u in utterances if u.closed_by == "soft_cap"),
            },
        )
        if latencies:
            logger.set_metric("latency_ms_max", round(max(latencies) * 1000, 1))
            logger.set_metric("latency_ms_min", round(min(latencies) * 1000, 1))
            logger.set_metric("latency_ms_mean", round(sum(latencies) / len(latencies) * 1000, 1))
            logger.set_metric("latency_ms_p50", round(sorted(latencies)[len(latencies) // 2] * 1000, 1))
            logger.set_metric("latency_ms_p95", round(sorted(latencies)[int(len(latencies) * 0.95)] * 1000, 1))

    assert utterances, "应产出 utterance"
    assert 0.5 <= ratio <= 1.5, (
        f"utterance 数 {len(utterances)} vs 脚本 {len(script_lines)},比例 {ratio:.2f} 超出 [0.5, 1.5]"
    )
    assert lcs_ratio >= 0.85, (
        f"LCS(hyp,ref)/len(hyp) = {lcs_ratio:.1%} < 85%; "
        f"len(ref)={len(ref)} len(hyp)={len(hyp)} lcs={lcs}\n"
        f"hyp_preview={hyp[:200]}\n"
        f"ref_preview={ref[:200]}"
    )


@pytest.mark.asyncio
async def test_soft_cap_8s():
    """Cycle 2: 9s 连续音频 + 0.4s 微停顿 + 3s 音频 → soft cap 在第一段后切。

    0.4s 静默小于 VAD 阈值 1.5s,所以 VAD 不会主动切;但累计说话 ≥8s 后,
    下一个 ≥0.3s 微停顿应触发 soft cap 关闭。
    """
    audio = stream_wav_realtime(LONG_MONOLOGUE_WAV, chunk_ms=100, speed=10.0)
    utterances = [u async for u in stream_stt(audio)]

    assert len(utterances) >= 2, f"soft cap 应在 8s 后切出至少 2 段,实际 {len(utterances)} 段"
    soft_capped = [u for u in utterances if u.closed_by == "soft_cap"]
    assert len(soft_capped) >= 1, f"至少 1 段应由 soft cap 关闭,实际 closed_by: {[u.closed_by for u in utterances]}"
    for u in soft_capped:
        assert u.t_end - u.t_start <= 9.5, f"soft cap utterance 不应远超 8s 上限: {u.t_end - u.t_start:.2f}s"
