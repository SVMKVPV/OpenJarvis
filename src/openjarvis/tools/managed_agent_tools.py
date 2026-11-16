"""Read the managed-agent roster and queue internal workstation handoffs."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

if TYPE_CHECKING:
    from openjarvis.agents.manager import AgentManager


class ManagedAgentListTool(BaseTool):
    tool_id = "managed_agent_list"

    def __init__(self, manager: AgentManager, sender: str) -> None:
        self._manager = manager
        self._sender = sender

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List managed agents eligible for an internal handoff.",
            parameters={"type": "object", "properties": {}},
            category="agents",
            required_capabilities=["system:admin"],
        )

    def execute(self, **params: Any) -> ToolResult:
        agents = [
            {field: record[field] for field in ("id", "name", "agent_type", "status")}
            for record in self._manager.list_agents()
            if record["id"] != self._sender
        ]
        return ToolResult(tool_name=self.tool_id, content=json.dumps(agents))


class ManagedAgentQueueTool(BaseTool):
    tool_id = "managed_agent_queue"

    def __init__(self, manager: AgentManager, sender: str) -> None:
        self._manager = manager
        self._sender = sender

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Queue a handoff for another managed agent's next run.",
            parameters={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Target agent ID."},
                    "message": {"type": "string", "description": "Task and context."},
                },
                "required": ["agent_id", "message"],
            },
            category="agents",
            required_capabilities=["system:admin"],
        )

    def execute(self, **params: Any) -> ToolResult:
        target, message = params.get("agent_id"), params.get("message")
        if not isinstance(target, str) or not isinstance(message, str):
            return ToolResult(
                tool_name=self.tool_id,
                content="Agent ID and message are required.",
                success=False,
            )
        message = message.strip()
        agent = self._manager.get_agent(target)
        sender = self._manager.get_agent(self._sender)
        if (
            not message
            or not agent
            or not sender
            or target == self._sender
            or agent["status"] == "archived"
        ):
            return ToolResult(
                tool_name=self.tool_id,
                content="Use another active agent and a message.",
                success=False,
            )
        note = (
            f"Internal handoff from {sender['name']} (agent {self._sender}):\n{message}"
        )
        handoff = self._manager.send_message(target, note, mode="handoff")
        return ToolResult(
            tool_name=self.tool_id,
            content=json.dumps(
                {"agent_id": target, "message_id": handoff["id"], "status": "queued"}
            ),
        )
