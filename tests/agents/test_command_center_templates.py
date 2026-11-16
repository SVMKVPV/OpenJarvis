from __future__ import annotations

from openjarvis.agents.manager import AgentManager


def test_command_center_role_templates_are_available() -> None:
    templates = {item["id"]: item for item in AgentManager.list_templates()}

    expected = {
        "cfo_finance",
        "competitive_research",
        "email_briefing",
        "quality_manager",
        "system_builder",
    }
    assert expected <= templates.keys()
    assert (
        "explicit CEO approval"
        in templates["cfo_finance"]["system_prompt_template"]
    )
    assert (
        "isolated branch or sandbox"
        in templates["system_builder"]["system_prompt_template"]
    )
