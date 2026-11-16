"""Unified command-center plugin catalog endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

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


@router.get("/{kind}/{plugin_id}")
async def get_plugin(kind: str, plugin_id: str) -> dict:
    item = PluginCatalog().get_plugin(kind, plugin_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return item.to_dict()


__all__ = ["router"]
