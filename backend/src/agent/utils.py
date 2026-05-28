"""Shared utilities for agent modules."""


def extract_json_from_markdown(content: str) -> str:
    """Strip markdown code fences if present."""
    if "```json" in content:
        return content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        return content.split("```")[1].split("```")[0].strip()
    return content
