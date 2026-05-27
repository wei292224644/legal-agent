import asyncio
import inspect

import pytest
from agno.models.openai import OpenAIChat

from agno_agents import (
    ANALYSIS_SYSTEM_PROMPT,
    EXECUTOR_SYSTEM_PROMPT,
    ExecutorItem,
    ExecutorOutput,
    ObserverItem,
    ObserverOutput,
    _parse_executor_response,
    _parse_observer_response,
    build_analyze_fn,
    build_execute_fn,
)
from agent import AnalysisResult, IntentResult
from audio_pipeline import TranscriptResult


class FakeResponse:
    """Simulate Agno run response with structured output."""
    def __init__(self, content):
        self.content = content


# ── Observer parser ────────────────────────────────────────────────────────────

def test_parse_observer_simple_from_dict():
    resp = FakeResponse({"intent": "simple", "category": "statute",
                         "title": "劳动法第82条", "content": "用人单位自用工之日起...",
                         "citation": "《劳动合同法》第82条", "level": ""})
    results = _parse_observer_response(resp)
    assert len(results) == 1
    r = results[0]
    assert isinstance(r, AnalysisResult)
    assert r.category == "statute"


def test_parse_observer_complex_from_dict():
    resp = FakeResponse({"intent": "complex", "question": "需要审查合同吗？",
                         "context": "没有签合同", "category": "contract",
                         "title": "", "content": "", "citation": "", "level": ""})
    results = _parse_observer_response(resp)
    assert len(results) == 1
    r = results[0]
    assert isinstance(r, IntentResult)
    assert r.question == "需要审查合同吗？"


def test_parse_observer_none_skipped():
    resp = FakeResponse({"intent": "none", "question": "", "context": "",
                         "category": "", "title": "", "content": "",
                         "citation": "", "level": ""})
    results = _parse_observer_response(resp)
    assert results == []


def test_parse_observer_mixed_list():
    resp = FakeResponse([
        {"intent": "simple", "category": "statute", "title": "法条", "content": "...",
         "citation": "X", "level": ""},
        {"intent": "complex", "question": "查合同？", "context": "...",
         "category": "contract", "title": "", "content": "", "citation": "", "level": ""},
        {"intent": "none", "question": "", "context": "",
         "category": "", "title": "", "content": "", "citation": "", "level": ""},
    ])
    results = _parse_observer_response(resp)
    assert len(results) == 2
    assert isinstance(results[0], AnalysisResult)
    assert isinstance(results[1], IntentResult)


# ── Executor parser ──────────────────────────────────────────────────────────

def test_parse_executor_single_from_dict():
    resp = FakeResponse({"category": "risk", "title": "合同风险",
                         "content": "未签劳动合同...", "citation": "",
                         "level": "高"})
    results = _parse_executor_response(resp)
    assert len(results) == 1
    assert results[0].category == "risk"
    assert results[0].level == "高"


def test_parse_executor_list():
    resp = FakeResponse([
        {"category": "statute", "title": "第82条", "content": "...",
         "citation": "劳动合同法", "level": ""},
        {"category": "contract", "title": "赔偿条款", "content": "...",
         "citation": "", "level": ""},
    ])
    results = _parse_executor_response(resp)
    assert len(results) == 2
    assert results[0].category == "statute"
    assert results[1].category == "contract"


def test_parse_executor_empty():
    resp = FakeResponse([])
    results = _parse_executor_response(resp)
    assert results == []


# ── Pydantic model parsing ────────────────────────────────────────────────────

def test_parse_observer_from_pydantic_output():
    output = ObserverOutput(items=[
        ObserverItem(intent="simple", category="statute", title="劳动法",
                     content="...", citation="X", level=""),
        ObserverItem(intent="complex", question="需要审查吗？", context="原文",
                     category="contract", title="", content="", citation="", level=""),
    ])
    resp = FakeResponse(output)
    results = _parse_observer_response(resp)
    assert len(results) == 2
    assert isinstance(results[0], AnalysisResult)
    assert isinstance(results[1], IntentResult)


def test_parse_executor_from_pydantic_output():
    output = ExecutorOutput(items=[
        ExecutorItem(category="statute", title="第82条", content="...",
                     citation="劳动合同法", level=""),
        ExecutorItem(category="risk", title="合同风险", content="未签合同",
                     citation="", level="高"),
    ])
    resp = FakeResponse(output)
    results = _parse_executor_response(resp)
    assert len(results) == 2
    assert results[0].category == "statute"
    assert results[1].level == "高"


# ── Factory signatures ────────────────────────────────────────────────────────

def test_build_analyze_fn_returns_coroutine_function():
    fn = build_analyze_fn()
    assert inspect.iscoroutinefunction(fn)
    # Verify signature: (list[TranscriptResult]) -> list[...]
    sig = inspect.signature(fn)
    assert len(sig.parameters) == 1


def test_build_execute_fn_returns_coroutine_function():
    fn = build_execute_fn()
    assert inspect.iscoroutinefunction(fn)
    sig = inspect.signature(fn)
    assert len(sig.parameters) == 2  # intent, context


# ── System prompts ────────────────────────────────────────────────────────────

def test_analysis_prompt_mentions_intent_types():
    assert "simple" in ANALYSIS_SYSTEM_PROMPT
    assert "complex" in ANALYSIS_SYSTEM_PROMPT
    assert "intent" in ANALYSIS_SYSTEM_PROMPT


def test_executor_prompt_mentions_categories():
    assert "statute" in EXECUTOR_SYSTEM_PROMPT
    assert "contract" in EXECUTOR_SYSTEM_PROMPT
    assert "risk" in EXECUTOR_SYSTEM_PROMPT
