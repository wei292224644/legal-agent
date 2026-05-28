import asyncio

import pytest
from datetime import datetime

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
        timestamp=datetime.now(),
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
                timestamp=datetime.now(),
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
        ProfileEntry(key="月薪", value="25000", timestamp=datetime.now(), source_utt_id="u_1"),
        ProfileEntry(key="工龄", value="2年", timestamp=datetime.now(), source_utt_id="u_2"),
        ProfileEntry(key="月薪", value="30000", timestamp=datetime.now(), source_utt_id="u_3"),
    ]
    for e in entries:
        await store.enqueue_profile_update(e.source_utt_id, [e])

    await asyncio.sleep(0.1)

    keys = store.get_profile_keys()
    assert sorted(keys) == ["工龄", "月薪"]

