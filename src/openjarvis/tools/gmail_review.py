"""Read the indexed Gmail review candidates used by the Command Center."""

from __future__ import annotations

import json

from openjarvis.connectors.store import KnowledgeStore
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("gmail_review_candidates")
class GmailReviewCandidatesTool(BaseTool):
    tool_id = "gmail_review_candidates"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=(
                "List up to 10 indexed Gmail threads whose latest inbox or sent "
                "message is inbound. Includes subject, sender, received time and "
                "message reference. A candidate may need no reply."
            ),
            parameters={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        )

    def execute(self) -> ToolResult:
        with KnowledgeStore() as store:
            candidates = store.gmail_review_candidates()
        return ToolResult(self.tool_id, json.dumps(candidates, ensure_ascii=False))


class GmailIndexedMessageTool(BaseTool):
    tool_id = "gmail_indexed_message"

    def __init__(self, store: KnowledgeStore) -> None:
        self._store = store

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Read an indexed Gmail message by exact reference.",
            parameters={
                "type": "object",
                "properties": {"reference": {"type": "string"}},
                "required": ["reference"],
            },
        )

    def execute(self, reference: str) -> ToolResult:
        message = self._store.gmail_indexed_message(reference)
        if message is None:
            return ToolResult(
                self.tool_id, "Indexed Gmail message not found.", success=False
            )
        return ToolResult(self.tool_id, json.dumps(message, ensure_ascii=False))
