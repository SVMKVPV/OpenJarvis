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


def test_finance_agent_inherits_indexed_search_guidance(tmp_path) -> None:
    manager = AgentManager(str(tmp_path / "agents.db"))
    try:
        record = manager.create_from_template(
            "cfo_finance", "Finance", {"schedule_type": "manual"}
        )
        prompt = record["config"]["system_prompt"]
        assert (
            "Gmail uses email, Google Drive uses document, and Obsidian uses note"
            in prompt
        )
        assert "Invoice and receipt are search terms" in prompt
        assert "knowledge_search" in record["config"]["tools"]
    finally:
        manager.close()
