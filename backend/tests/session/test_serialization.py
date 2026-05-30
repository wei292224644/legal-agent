"""序列化往返测试：确保 Agent 状态可完整恢复。"""

import asyncio

import numpy as np
import pytest

from agent.context_store import ContextStore, ProfileEntry
from agent.orchestrator import Orchestrator, PendingRequest
from diarization.enrollment import Enrollment
from models.utterance import Utterance


@pytest.mark.asyncio
class TestContextStoreRoundtrip:
    async def test_empty(self):
        ctx = ContextStore()
        d = ctx.to_dict()
        ctx2 = ContextStore.from_dict(d)
        assert ctx2.get_generation() == 0
        assert ctx2.get_full_history() == []
        assert ctx2.get_profile() == []

    async def test_with_utterances_and_profile(self):
        ctx = ContextStore()
        await ctx.start_profile_worker()
        await ctx.append_utterance(Utterance(id="u1", text="hello", t_start=0.0, t_end=1.0, speaker="client"))
        await ctx.append_utterance(Utterance(id="u2", text="world", t_start=1.0, t_end=2.0, speaker="lawyer"))
        await ctx.enqueue_profile_update("u1", [ProfileEntry(key="name", value="Alice", timestamp=0.0, source_utt_id="u1")])
        # 等 worker 消费
        await asyncio.sleep(0.1)
        await ctx.stop_profile_worker()

        d = ctx.to_dict()
        ctx2 = ContextStore.from_dict(d)
        assert ctx2.get_generation() == 2
        assert len(ctx2.get_full_history()) == 2
        assert ctx2.get_full_history()[0].text == "hello"
        assert ctx2.get_full_history()[1].speaker == "lawyer"
        assert len(ctx2.get_profile()) == 1
        assert ctx2.get_profile()[0].key == "name"


class TestOrchestratorRoundtrip:
    @pytest.mark.asyncio
    async def test_empty(self):
        ctx = ContextStore()
        orch = Orchestrator(ctx)
        d = orch.to_dict()
        orch2 = Orchestrator.from_dict(d, ctx=ctx)
        assert orch2._pending == {}

    @pytest.mark.asyncio
    async def test_with_pending(self):
        """to_dict 把 pending 写进 snapshot 供审计;from_dict 故意不恢复——
        RunOutput 含不可序列化的运行期对象,跨进程恢复无法 confirm。
        见 PendingRequest / Orchestrator.from_dict docstring。"""
        ctx = ContextStore()
        orch = Orchestrator(ctx)
        orch._pending["req_1"] = PendingRequest(
            request_id="req_1",
            run_id="run_abc",
            utt_id="u1",
            generation=1,
            preview={"topic": "胜率评估", "rationale": "全画像"},
        )
        d = orch.to_dict()
        assert any(p["request_id"] == "req_1" for p in d["pending"]), "snapshot 应记录 pending(审计用)"
        orch2 = Orchestrator.from_dict(d, ctx=ctx)
        assert orch2._pending == {}, "恢复后必须为空,避免对失效 RunOutput 调 confirm"


class TestEnrollmentRoundtrip:
    def test_full(self):
        emb = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        client_emb = np.array([0.4, 0.5], dtype=np.float32)
        e = Enrollment(
            embedding=emb,
            tau_high=0.6,
            tau_low=0.2,
            client_embedding=client_emb,
            margin=0.15,
            seed_threshold=0.45,
            seed_min_duration_s=2.5,
        )
        d = e.to_dict()
        e2 = Enrollment.from_dict(d)
        np.testing.assert_array_equal(e2.embedding, emb)
        assert e2.tau_high == 0.6
        assert e2.tau_low == 0.2
        np.testing.assert_array_equal(e2.client_embedding, client_emb)
        assert e2.margin == 0.15

    def test_no_client_embedding(self):
        e = Enrollment(embedding=np.array([0.1], dtype=np.float32))
        d = e.to_dict()
        e2 = Enrollment.from_dict(d)
        assert e2.client_embedding is None


class TestUtteranceRoundtrip:
    def test_basic(self):
        u = Utterance(id="u1", text="hello", t_start=0.0, t_end=1.0, speaker="client")
        d = u.to_dict()
        u2 = Utterance.from_dict(d)
        assert u2.id == "u1"
        assert u2.text == "hello"
        assert u2.speaker == "client"
        assert u2.closed_by == "vad"

    def test_none_speaker(self):
        u = Utterance(id="u1", text="x", t_start=0.0, t_end=1.0, speaker=None)
        d = u.to_dict()
        u2 = Utterance.from_dict(d)
        assert u2.speaker is None
