import asyncio
from datetime import datetime

import pytest

from agent.context_store import ContextStore, ProfileEntry
from models.utterance import Utterance


@pytest.mark.asyncio
async def test_append_utterance_returns_incrementing_generation():
    store = ContextStore()
    utt1 = Utterance(
        id="u_1",
        text="hello",
        speaker="client",
        t_start=0.0,
        t_end=1.0,
        timestamp=datetime.now(),
    )
    utt2 = Utterance(
        id="u_2",
        text="world",
        speaker="lawyer",
        t_start=1.0,
        t_end=2.0,
        timestamp=datetime.now(),
    )

    g1 = await store.append_utterance(utt1)
    g2 = await store.append_utterance(utt2)

    assert g1 == 1
    assert g2 == 2
    assert len(store.get_full_history()) == 2


@pytest.mark.asyncio
async def test_get_recent_window_returns_last_n_utterances():
    store = ContextStore()
    for i in range(10):
        utt = Utterance(
            id=f"u_{i}",
            text=f"text_{i}",
            speaker="client",
            t_start=float(i),
            t_end=float(i + 1),
            timestamp=datetime.now(),
        )
        await store.append_utterance(utt)

    window = store.get_recent_window(n=8)
    assert len(window) == 8
    assert window[0].id == "u_2"
    assert window[-1].id == "u_9"


@pytest.mark.asyncio
async def test_profile_worker_appends_entries():
    store = ContextStore()
    await store.start_profile_worker()

    entry = ProfileEntry(
        key="月薪",
        value="25000",
        timestamp=0.0,
        source_utt_id="u_1",
        confidence=1.0,
    )
    await store.enqueue_profile_update("u_1", [entry])

    # wait for worker to process
    await asyncio.sleep(0.1)

    profile = store.get_profile()
    assert len(profile) == 1
    assert profile[0].key == "月薪"
    assert profile[0].value == "25000"


@pytest.mark.asyncio
async def test_profile_worker_preserves_order_under_concurrent_enqueue():
    store = ContextStore()
    await store.start_profile_worker()

    async def enqueue_batch(batch_id: int):
        for i in range(5):
            entry = ProfileEntry(
                key=f"batch_{batch_id}",
                value=f"item_{i}",
                timestamp=float(batch_id * 5 + i),
                source_utt_id=f"u_{batch_id}_{i}",
                confidence=1.0,
            )
            await store.enqueue_profile_update(f"u_{batch_id}_{i}", [entry])

    await asyncio.gather(enqueue_batch(0), enqueue_batch(1), enqueue_batch(2))

    await asyncio.sleep(0.2)

    profile = store.get_profile()
    assert len(profile) == 15

    for batch_id in range(3):
        batch_entries = [e for e in profile if e.key == f"batch_{batch_id}"]
        assert len(batch_entries) == 5
        values = [e.value for e in batch_entries]
        assert values == [f"item_{i}" for i in range(5)]


@pytest.mark.asyncio
async def test_get_profile_keys_returns_unique_keys():
    store = ContextStore()
    await store.start_profile_worker()

    entries = [
        ProfileEntry(key="月薪", value="25000", timestamp=1.0, source_utt_id="u_1"),
        ProfileEntry(key="工龄", value="2年", timestamp=2.0, source_utt_id="u_2"),
        ProfileEntry(key="月薪", value="30000", timestamp=3.0, source_utt_id="u_3"),
    ]
    for e in entries:
        await store.enqueue_profile_update(e.source_utt_id, [e])

    await asyncio.sleep(0.1)

    keys = store.get_profile_keys()
    assert sorted(keys) == ["工龄", "月薪"]


def test_get_profile_sorted():
    """get_profile() 应按 timestamp 升序返回。"""
    store = ContextStore()
    store._profile = [
        ProfileEntry(key="a", value="1", timestamp=3.0, source_utt_id="u3"),
        ProfileEntry(key="b", value="2", timestamp=1.0, source_utt_id="u1"),
        ProfileEntry(key="c", value="3", timestamp=2.0, source_utt_id="u2"),
    ]
    profile = store.get_profile()
    timestamps = [e.timestamp for e in profile]
    assert timestamps == [1.0, 2.0, 3.0]


def test_get_profile_keys_sorted():
    """get_profile_keys() 应按 timestamp 降序去重，保留每个 key 的最新出现。"""
    store = ContextStore()
    store._profile = [
        ProfileEntry(key="月薪", value="25000", timestamp=1.0, source_utt_id="u1"),
        ProfileEntry(key="工龄", value="2年", timestamp=2.0, source_utt_id="u2"),
        ProfileEntry(key="月薪", value="30000", timestamp=3.0, source_utt_id="u3"),
    ]
    keys = store.get_profile_keys()
    assert keys == ["月薪", "工龄"]


def test_get_generation():
    """get_generation() 应返回当前 generation 编号。"""
    store = ContextStore()
    assert store.get_generation() == 0
    store._generation = 5
    assert store.get_generation() == 5


@pytest.mark.asyncio
async def test_get_recent_window_zero_returns_empty():
    """n <= 0 时 get_recent_window() 应返回空列表。"""
    store = ContextStore()
    utt = Utterance(
        id="u_1",
        text="hello",
        speaker="client",
        t_start=0.0,
        t_end=1.0,
        timestamp=datetime.now(),
    )
    await store.append_utterance(utt)
    assert store.get_recent_window(n=0) == []
    assert store.get_recent_window(n=-1) == []


def test_profile_entry_category():
    """ProfileEntry 应支持 category 字段。"""
    entry = ProfileEntry(
        key="月薪", value="25000", timestamp=0.0, source_utt_id="u1", category="收入"
    )
    assert entry.category == "收入"

    entry_default = ProfileEntry(
        key="工龄", value="2年", timestamp=0.0, source_utt_id="u1"
    )
    assert entry_default.category is None
