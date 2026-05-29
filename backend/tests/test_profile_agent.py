import pytest

from agent.profile_agent import ProfileAgent


@pytest.mark.asyncio
async def test_extracts_salary_with_number(mock_llm_client):
    client = mock_llm_client('{"entries": [{"key": "月薪", "value": "两万五"}]}')
    agent = ProfileAgent(client=client)
    entries = await agent.extract("月薪两万五，税前", "client", [], {})
    assert len(entries) >= 1
    assert entries[0].key == "月薪"
    assert "两万" in entries[0].value or "25000" in entries[0].value


@pytest.mark.asyncio
async def test_skips_vague_values_without_numbers(mock_llm_client):
    """PA should not extract '工作多久' or '大概多少' as factual values."""
    client = mock_llm_client('{"entries": []}')
    agent = ProfileAgent(client=client)
    entries = await agent.extract("你工作多久了？", "client", [], {})
    for e in entries:
        assert e.value not in ("多久", "工作多久", "大概多少", "大概")


@pytest.mark.asyncio
async def test_skips_question_phrases(mock_llm_client):
    """Questions should not produce profile entries."""
    client = mock_llm_client('{"entries": []}')
    agent = ProfileAgent(client=client)
    entries = await agent.extract("月薪大概多少？", "client", [], {})
    for e in entries:
        assert "大概" not in e.value
        assert "多少" not in e.value


@pytest.mark.asyncio
async def test_extracts_date_from_exact_phrase(mock_llm_client):
    client = mock_llm_client('{"entries": [{"key": "入职日期", "value": "2024年2月17号"}]}')
    agent = ProfileAgent(client=client)
    entries = await agent.extract("2024年2月17号入职的", "client", [], {})
    keys = [e.key for e in entries]
    assert any("入职" in k or "日期" in k for k in keys)


@pytest.mark.asyncio
async def test_does_not_duplicate_existing_key(mock_llm_client):
    """When key already exists, should not extract duplicate."""
    client = mock_llm_client('{"entries": []}')
    agent = ProfileAgent(client=client)
    entries = await agent.extract("月薪两万五", "client", [], {"月薪": "两万五"})
    salary_entries = [e for e in entries if e.key == "月薪"]
    assert len(salary_entries) == 0  # Should not add again when already known


@pytest.mark.asyncio
async def test_skips_lawyer_questions(mock_llm_client):
    """Lawyer asking questions should not produce profile entries."""
    client = mock_llm_client('{"entries": []}')
    agent = ProfileAgent(client=client)
    entries = await agent.extract("你工作多久了？", "lawyer", [], {})
    assert len(entries) == 0


@pytest.mark.asyncio
async def test_skips_lawyer_questions_even_with_existing_keys(mock_llm_client):
    """Regression: when existing_keys is non-empty, lawyer questions must still be skipped."""
    client = mock_llm_client('{"entries": []}')
    agent = ProfileAgent(client=client)
    existing = {"辞退原因": "违法解除", "辞退通知时间": "2024-05-01", "离职要求": "赔偿"}
    entries = await agent.extract("你工作多久了？月薪大概多少？", "lawyer", [], existing)
    for e in entries:
        assert e.value not in ("工作多久", "大概多少", "多久", "多少")


@pytest.mark.asyncio
async def test_skips_greetings(mock_llm_client):
    """Greetings and small talk should not produce entries."""
    client = mock_llm_client('{"entries": []}')
    agent = ProfileAgent(client=client)
    entries = await agent.extract("律师你好，我是朋友介绍来的", "client", [], {})
    assert len(entries) == 0


def test_parse_response_invalid_json_returns_empty(mock_llm_client):
    """Regression: _parse_response should return [] on invalid JSON instead of crashing."""
    client = mock_llm_client('{"entries": []}')
    agent = ProfileAgent(client=client)
    result = agent._parse_response("not json at all", utt_id="u_1")
    assert result == []


def test_parse_response_missing_entries_key_returns_empty(mock_llm_client):
    """_parse_response should return [] when JSON lacks 'entries' key."""
    client = mock_llm_client('{"entries": []}')
    agent = ProfileAgent(client=client)
    result = agent._parse_response('{"data": []}', utt_id="u_1")
    assert result == []
