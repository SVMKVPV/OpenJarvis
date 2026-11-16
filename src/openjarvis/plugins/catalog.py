"""Read-only catalog spanning built-ins and installed extension entry points.

OpenJarvis already has typed registries for connectors, channels, tools,
agents, and inference engines.  This module presents them through one stable
plugin model so the command center can configure capabilities without knowing
which internal registry owns each one.

Third-party entry points are intentionally *discovered but not imported*.
Importing an extension executes its Python code, so activation belongs behind
an explicit security review and approval flow rather than a catalog request.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import asdict, dataclass
from importlib import metadata
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class PluginDescriptor:
    """Serializable metadata for one command-center plugin."""

    id: str
    name: str
    kind: str
    source: str
    installed: bool
    enabled: bool
    auth_type: str = "none"
    description: str = ""
    package: str = "openjarvis"
    version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _RegistrySpec:
    kind: str
    module: str
    registry_name: str
    entry_point_group: str


_REGISTRY_SPECS: Sequence[_RegistrySpec] = (
    _RegistrySpec(
        "connector",
        "openjarvis.connectors",
        "ConnectorRegistry",
        "openjarvis.connectors",
    ),
    _RegistrySpec(
        "channel", "openjarvis.channels", "ChannelRegistry", "openjarvis.channels"
    ),
    _RegistrySpec("tool", "openjarvis.tools", "ToolRegistry", "openjarvis.tools"),
    _RegistrySpec("agent", "openjarvis.agents", "AgentRegistry", "openjarvis.agents"),
    _RegistrySpec(
        "engine", "openjarvis.engine", "EngineRegistry", "openjarvis.engines"
    ),
)


def _humanize(value: str) -> str:
    return value.replace("-", " ").replace("_", " ").strip().title()


def _description(entry: Any) -> str:
    explicit = getattr(entry, "description", "")
    if explicit:
        return str(explicit).strip()
    doc = getattr(entry, "__doc__", "") or ""
    return doc.strip().split("\n\n", 1)[0].replace("\n", " ")


def _entry_points_for(group: str) -> Iterable[Any]:
    points = metadata.entry_points()
    if hasattr(points, "select"):
        return points.select(group=group)
    if isinstance(points, Mapping):
        return points.get(group, ())
    return (point for point in points if getattr(point, "group", None) == group)


class PluginCatalog:
    """Build a deterministic catalog without executing third-party code."""

    def __init__(self, specs: Sequence[_RegistrySpec] = _REGISTRY_SPECS) -> None:
        self._specs = tuple(specs)

    def list_plugins(self, *, kind: str | None = None) -> list[PluginDescriptor]:
        descriptors: dict[tuple[str, str], PluginDescriptor] = {}
        for spec in self._specs:
            if kind and spec.kind != kind:
                continue
            for item in self._builtins(spec):
                descriptors[(item.kind, item.id)] = item
            for item in self._extensions(spec):
                descriptors.setdefault((item.kind, item.id), item)
        return sorted(
            descriptors.values(),
            key=lambda item: (item.kind, item.name.lower(), item.id),
        )

    def get_plugin(self, kind: str, plugin_id: str) -> PluginDescriptor | None:
        return next(
            (item for item in self.list_plugins(kind=kind) if item.id == plugin_id),
            None,
        )

    @staticmethod
    def _builtins(spec: _RegistrySpec) -> Iterable[PluginDescriptor]:
        try:
            importlib.import_module(spec.module)
            registry_module = importlib.import_module("openjarvis.core.registry")
            registry = getattr(registry_module, spec.registry_name)
            # Test isolation and long-lived plugin hosts may clear a registry
            # after its decorator modules have already been cached. Re-run
            # connector decorators in that narrow case; ordinary requests do
            # no reload work because the registry is already populated.
            if spec.kind == "connector" and not registry.keys():
                ignored_suffixes = {
                    "_stubs",
                    "attachment_store",
                    "chunker",
                    "embedding_store",
                    "embeddings",
                    "google_auth",
                    "hybrid_search",
                    "oauth",
                    "pipeline",
                    "retriever",
                    "scheduler",
                    "store",
                    "sync_engine",
                }
                prefix = f"{spec.module}."
                for module_name in sorted(sys.modules):
                    if not module_name.startswith(prefix):
                        continue
                    if module_name.rsplit(".", 1)[-1] in ignored_suffixes:
                        continue
                    module = sys.modules.get(module_name)
                    if module is not None:
                        importlib.reload(module)
        except (ImportError, AttributeError):
            return ()

        result: list[PluginDescriptor] = []
        for plugin_id, entry in registry.items():
            name = (
                getattr(entry, "display_name", "")
                or getattr(entry, "name", "")
                or getattr(entry, "tool_id", "")
                or _humanize(plugin_id)
            )
            result.append(
                PluginDescriptor(
                    id=plugin_id,
                    name=str(name),
                    kind=spec.kind,
                    source="built-in",
                    installed=True,
                    enabled=True,
                    auth_type=str(getattr(entry, "auth_type", "none")),
                    description=_description(entry),
                )
            )
        return result

    @staticmethod
    def _extensions(spec: _RegistrySpec) -> Iterable[PluginDescriptor]:
        result: list[PluginDescriptor] = []
        try:
            points = _entry_points_for(spec.entry_point_group)
        except Exception:
            return result

        for point in points:
            distribution = getattr(point, "dist", None)
            package = getattr(distribution, "name", "") or getattr(point, "module", "")
            version = getattr(distribution, "version", "") or ""
            result.append(
                PluginDescriptor(
                    id=str(point.name),
                    name=_humanize(str(point.name)),
                    kind=spec.kind,
                    source="extension",
                    installed=True,
                    enabled=False,
                    description=(
                        "Installed extension; activation requires an explicit "
                        "security review and approval."
                    ),
                    package=str(package),
                    version=str(version),
                )
            )
        return result


__all__ = ["PluginCatalog", "PluginDescriptor"]
