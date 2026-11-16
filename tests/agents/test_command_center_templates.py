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
        "general_manager",
        "operations_manager",
    }
    assert expected <= templates.keys()
    for role in ("general_manager", "operations_manager"):
        assert templates[role]["schedule_type"] == "manual"
        assert templates[role]["tools"] == []
        assert "report to Dot" in templates[role]["system_prompt_template"]
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


def test_quality_manager_queues_a_managed_workstation_handoff(tmp_path) -> None:
    import json

    from openjarvis.agents.tool_resolver import resolve_agent_tools

    manager = AgentManager(str(tmp_path / "agents.db"))
    try:
        reviewer = manager.create_from_template("quality_manager", "Managers")
        worker = manager.create_agent("Marketing", config={"schedule_type": "manual"})
        with resolve_agent_tools(
            reviewer, engine=object(), model="local", agent_manager=manager
        ) as toolkit:
            roster = toolkit.by_name["managed_agent_list"].execute()
            assert [item["id"] for item in json.loads(roster.content)] == [worker["id"]]
            handoff = toolkit.by_name["managed_agent_queue"].execute(
                agent_id=worker["id"],
                message="Correct the headline and return a draft.",
            )
            assert handoff.success
            queued = manager.get_pending_messages(worker["id"])
            assert [message["id"] for message in queued] == [
                json.loads(handoff.content)["message_id"]
            ]
            assert queued[0]["mode"] == "handoff"
            assert queued[0]["content"].startswith("Internal handoff from Managers")
            assert manager.get_agent(worker["id"])["status"] == "idle"
    finally:
        manager.close()
