"""funasr_stream_v2 最小测试：接口一致 + 可导入执行。"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from stt.funasr_stream import stream_stt
from stt.funasr_stream_v2 import stream_stt_v2


def test_stream_stt_v2_signature_matches_v1():
    """v2 外部接口必须与 v1 完全一致。"""
    sig_v1 = inspect.signature(stream_stt)
    sig_v2 = inspect.signature(stream_stt_v2)
    assert sig_v1 == sig_v2


@pytest.mark.asyncio
async def test_stream_stt_v2_empty_input():
    """空输入流不应产出任何 utterance，也不应抛异常。"""

    async def empty_chunks():
        if False:
            yield np.zeros(0, dtype=np.float32), 0.0

    utts = []
    async for utt in stream_stt_v2(empty_chunks(), enrollment=None):
        utts.append(utt)
    assert utts == []
