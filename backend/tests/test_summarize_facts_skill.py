"""Tests for Agno skills — verify SKILL.md files are valid and loadable."""

from pathlib import Path

from agno.skills import LocalSkills

SKILLS_DIR = Path(__file__).parent.parent / "src" / "agent" / "skills"


def test_skills_directory_exists():
    assert SKILLS_DIR.exists()
    assert SKILLS_DIR.is_dir()


def test_compute_compensation_skill_loads():
    loader = LocalSkills(str(SKILLS_DIR / "compute-compensation"))
    skills = loader.load()
    assert len(skills) == 1
    skill = skills[0]
    assert skill.name == "compute-compensation"
    assert "N（经济补偿金）" in skill.instructions
    assert "2N（违法解除赔偿金）" in skill.instructions


def test_summarize_facts_skill_loads():
    loader = LocalSkills(str(SKILLS_DIR / "summarize-facts"))
    skills = loader.load()
    assert len(skills) == 1
    skill = skills[0]
    assert skill.name == "summarize-facts"
    assert "劳动关系基本信息" in skill.instructions
    assert "风险点" in skill.instructions


def test_all_skills_load_from_parent_dir():
    loader = LocalSkills(str(SKILLS_DIR))
    skills = loader.load()
    names = {s.name for s in skills}
    assert "compute-compensation" in names
    assert "summarize-facts" in names
