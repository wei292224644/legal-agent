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


def test_risk_triage_skill_loads():
    loader = LocalSkills(str(SKILLS_DIR / "risk-triage"))
    skills = loader.load()
    assert len(skills) == 1
    skill = skills[0]
    assert skill.name == "risk-triage"
    assert "初步评级" in skill.instructions


def test_chronology_builder_skill_loads():
    loader = LocalSkills(str(SKILLS_DIR / "chronology-builder"))
    skills = loader.load()
    assert len(skills) == 1
    skill = skills[0]
    assert skill.name == "chronology-builder"
    assert "时间线" in skill.instructions


def test_matter_intake_skill_loads():
    loader = LocalSkills(str(SKILLS_DIR / "matter-intake"))
    skills = loader.load()
    assert len(skills) == 1
    skill = skills[0]
    assert skill.name == "matter-intake"
    assert "Conflicts" in skill.instructions


def test_demand_intake_skill_loads():
    loader = LocalSkills(str(SKILLS_DIR / "demand-intake"))
    skills = loader.load()
    assert len(skills) == 1
    skill = skills[0]
    assert skill.name == "demand-intake"
    assert "Posture for this matter" in skill.instructions


def test_demand_draft_skill_loads():
    loader = LocalSkills(str(SKILLS_DIR / "demand-draft"))
    skills = loader.load()
    assert len(skills) == 1
    skill = skills[0]
    assert skill.name == "demand-draft"
    assert "Pre-draft gate" in skill.instructions


def test_client_intake_skill_loads():
    loader = LocalSkills(str(SKILLS_DIR / "client-intake"))
    skills = loader.load()
    assert len(skills) == 1
    skill = skills[0]
    assert skill.name == "client-intake"
    assert "Conflict check flags" in skill.instructions


def test_socratic_drill_skill_loads():
    loader = LocalSkills(str(SKILLS_DIR / "socratic-drill"))
    skills = loader.load()
    assert len(skills) == 1
    skill = skills[0]
    assert skill.name == "socratic-drill"
    assert "real-matter check" in skill.instructions


def test_legal_memo_skill_loads():
    loader = LocalSkills(str(SKILLS_DIR / "legal-memo"))
    skills = loader.load()
    assert len(skills) == 1
    skill = skills[0]
    assert skill.name == "legal-memo"
    assert "IRAC" in skill.instructions


def test_all_skills_load_from_parent_dir():
    loader = LocalSkills(str(SKILLS_DIR))
    skills = loader.load()
    names = {s.name for s in skills}
    assert "compute-compensation" in names
    assert "summarize-facts" in names
    assert "risk-triage" in names
    assert "matter-intake" in names
    assert "client-intake" in names
    assert "chronology-builder" in names
    assert "demand-intake" in names
    assert "demand-draft" in names
    assert "socratic-drill" in names
    assert "legal-memo" in names
