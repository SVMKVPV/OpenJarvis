"""Unified command-center plugin catalog endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from openjarvis.plugins import PluginCatalog

router = APIRouter(prefix="/v1/plugins", tags=["plugins"])


@router.get("")
async def list_plugins(kind: str | None = Query(default=None)) -> dict:
    items = PluginCatalog().list_plugins(kind=kind)
    return {
        "plugins": [item.to_dict() for item in items],
        "count": len(items),
        "kinds": sorted({item.kind for item in items}),
    }


@router.post("/mcp/discover")
def discover_mcp_tools(request: Request) -> dict:
    from openjarvis.server.agent_manager_routes import _get_mcp_tools

    state = request.app.state
    _, tools = _get_mcp_tools(state)
    return {
        "tool_count": len(tools),
        "tool_names": sorted(tools),
        "servers": getattr(state, "_mcp_discovery_outcomes", []),
    }


@router.get("/{kind}/{plugin_id}")
async def get_plugin(kind: str, plugin_id: str) -> dict:
    item = PluginCatalog().get_plugin(kind, plugin_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return item.to_dict()


__all__ = ["router"]
