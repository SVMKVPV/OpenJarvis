"""Expose the saved Shared Brain brief to a local MCP client over stdio."""

from __future__ import annotations

import json
import os
import sys
from typing import Any
from urllib.parse import urlsplit

import httpx

from openjarvis.core.types import ToolResult
from openjarvis.mcp.protocol import INVALID_REQUEST, MCPRequest, MCPResponse
from openjarvis.mcp.server import MCPServer
from openjarvis.tools._stubs import BaseTool, ToolSpec


class ReadSharedBrief(BaseTool):
    tool_id = "read_shared_brain_brief"

    def __init__(self, url: str, key: str) -> None:
        self._url = url.rstrip("/") + "/v1/shared-brain/brief"
        self._key = key

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Read the saved Shared Brain brief and its revision.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            response = httpx.get(
                self._url,
                headers={"Authorization": f"Bearer {self._key}"},
                timeout=10.0,
                follow_redirects=False,
                trust_env=False,
            )
            response.raise_for_status()
            brief = response.json()
            context, revision = brief["context"], brief["revision"]
            if not isinstance(context, str) or type(revision) is not int:
                raise ValueError("Invalid brief")
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return ToolResult(
                tool_name=self.tool_id, success=False,
                content="Could not read the Shared Brain brief. Check the backend URL and read key.",
            )
        return ToolResult(
            tool_name=self.tool_id,
            content=json.dumps({"context": context, "revision": revision}),
        )


def main() -> int:
    url = os.environ.get("OPENJARVIS_SHARED_BRAIN_URL", "").strip()
    key = os.environ.get("OPENJARVIS_SHARED_BRAIN_READ_KEY", "").strip()
    parsed = urlsplit(url)
    loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if (
        not key or not parsed.hostname or parsed.username is not None
        or parsed.query or parsed.fragment
        or not (parsed.scheme == "https" or (parsed.scheme == "http" and loopback))
    ):
        print("Configure the Shared Brain backend URL and read key.", file=sys.stderr)
        return 2

    server = MCPServer(tools=[ReadSharedBrief(url, key)])
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if not isinstance(message, dict) or not isinstance(message.get("method"), str):
                raise ValueError("Invalid request")
            if "id" not in message:
                continue
            request = MCPRequest.from_json(line)
            if not isinstance(request.params, dict):
                raise ValueError("Invalid parameters")
        except (ValueError, TypeError):
            response = MCPResponse.error_response(None, INVALID_REQUEST, "Invalid MCP request")
        else:
            response = server.handle(request)
        print(response.to_json(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
