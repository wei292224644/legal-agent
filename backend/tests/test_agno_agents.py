import inspect

import pytest

from agno_agents import (
    ANALYSIS_SYSTEM_PROMPT,
    EXECUTOR_SYSTEM_PROMPT,
    ExecutorItem,
    ExecutorOutput,
    ObserverItem,
    ObserverOutput,
    _format_profile,
    _parse_executor_response,
    _parse_observer_response,
    build_analyze_fn,
    build_execute_fn,
)
from agent import AnalysisResult, IntentResult


class FakeResponse:
    def __init__(self, content):
        self.content = content


# ── Observer parser ────────────────────────────────────────────────────────────

def test_parse_observer_simple_from_pydantic():
    output = ObserverOutput(
        facts_summary="合同未签",
        items=[ObserverItem(intent="simple", category="statute", title="劳动法",
                           content="...", citation="X", level="")],
    )
    resp = FakeResponse(output)
    facts, results = _parse_observer_response(resp)
    assert facts == "合同未签"
    assert len(results) == 1
    assert isinstance(results[0], AnalysisResult)


def test_parse_observer_complex_from_pydantic():
    output = ObserverOutput(
        facts_summary="",
        items=[ObserverItem(intent="complex", question="需要审查吗？", context="原文",
                           category="", title="", content="", citation="", level="")],
    )
    resp = FakeResponse(output)
    facts, results = _parse_observer_response(resp)
    assert len(results) == 1
    assert isinstance(results[0], IntentResult)


def test_parse_observer_none_skipped():
    output = ObserverOutput(
        facts_summary="无",
        items=[ObserverItem(intent="none", question="", context="",
                           category="", title="", content="", citation="", level="")],
    )
    resp = FakeResponse(output)
    _, results = _parse_observer_response(resp)
    assert results == []


def test_parse_observer_from_dict():
    resp = FakeResponse({"facts_summary": "事实", "items": [
        {"intent": "simple", "category": "statute", "title": "法条", "content": "...",
         "citation": "X", "level": ""},
        {"intent": "complex", "question": "查合同？", "context": "...",
         "category": "", "title": "", "content": "", "citation": "", "level": ""},
    ]})
    facts, results = _parse_observer_response(resp)
    assert facts == "事实"
    assert len(results) == 2


# ── Executor parser ──────────────────────────────────────────────────────────

def test_parse_executor_from_pydantic():
    output = ExecutorOutput(items=[
        ExecutorItem(category="statute", title="第82条", content="...",
                     citation="劳动合同法", level=""),
        ExecutorItem(category="risk", title="合同风险", content="...",
                     citation="", level="高"),
    ])
    resp = FakeResponse(output)
    results = _parse_executor_response(resp)
    assert len(results) == 2
    assert results[0].category == "statute"
    assert results[1].level == "高"


def test_parse_executor_from_list():
    resp = FakeResponse([
        {"category": "statute", "title": "X", "content": "...", "citation": "", "level": ""},
    ])
    results = _parse_executor_response(resp)
    assert len(results) == 1


def test_parse_executor_empty():
    resp = FakeResponse([])
    results = _parse_executor_response(resp)
    assert results == []


# ── Profile formatting ───────────────────────────────────────────────────────

def test_format_profile_empty():
    assert _format_profile({}) == ""


def test_format_profile_with_entries():
    profile = {
        "contract": [
            {"value": "未签", "ts": "2024-03-15T10:00:00"},
        ],
        "入职日期": [
            {"value": "2024.03.15", "ts": "2024-03-15T09:00:00"},
        ],
    }
    text = _format_profile(profile)
    assert "contract: 未签" in text
    assert "入职日期: 2024.03.15" in text


# ── Factory signatures ────────────────────────────────────────────────────────

def test_build_analyze_fn_returns_coroutine_function():
    fn = build_analyze_fn()
    assert inspect.iscoroutinefunction(fn)
    sig = inspect.signature(fn)
    assert len(sig.parameters) == 2  # profile, context


def test_build_execute_fn_returns_coroutine_function():
    fn = build_execute_fn()
    assert inspect.iscoroutinefunction(fn)
    sig = inspect.signature(fn)
    assert len(sig.parameters) == 2


# ── System prompts ────────────────────────────────────────────────────────────

def test_analysis_prompt_mentions_facts():
    assert "facts_summary" in ANALYSIS_SYSTEM_PROMPT
    assert "simple" in ANALYSIS_SYSTEM_PROMPT
    assert "complex" in ANALYSIS_SYSTEM_PROMPT


def test_executor_prompt_mentions_categories():
    assert "statute" in EXECUTOR_SYSTEM_PROMPT
    assert "contract" in EXECUTOR_SYSTEM_PROMPT
    assert "risk" in EXECUTOR_SYSTEM_PROMPT
