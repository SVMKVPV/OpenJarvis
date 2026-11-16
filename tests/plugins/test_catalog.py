from __future__ import annotations

from types import SimpleNamespace

from openjarvis.plugins.catalog import PluginCatalog, _entry_points_for


def test_catalog_exposes_builtin_connectors_as_plugins() -> None:
    plugins = PluginCatalog().list_plugins(kind="connector")
    by_id = {item.id: item for item in plugins}

    assert "gmail" in by_id
    assert by_id["gmail"].kind == "connector"
    assert by_id["gmail"].source == "built-in"
    assert by_id["gmail"].enabled is True
    assert by_id["gmail"].auth_type == "oauth"


def test_catalog_can_find_one_plugin() -> None:
    plugin = PluginCatalog().get_plugin("connector", "news_rss")

    assert plugin is not None
    assert plugin.name == "News / RSS"


def test_entry_point_discovery_does_not_load_extension(monkeypatch) -> None:
    loaded = False

    class FakePoint:
        name = "custom_crm"
        group = "openjarvis.connectors"
        module = "example_plugin"
        dist = SimpleNamespace(name="example-plugin", version="1.2.3")

        def load(self):
            nonlocal loaded
            loaded = True
            raise AssertionError("catalog discovery must not execute plugin code")

    class FakePoints(list):
        def select(self, *, group: str):
            return [point for point in self if point.group == group]

    monkeypatch.setattr(
        "openjarvis.plugins.catalog.metadata.entry_points",
        lambda: FakePoints([FakePoint()]),
    )

    assert list(_entry_points_for("openjarvis.connectors"))
    plugin = PluginCatalog().get_plugin("connector", "custom_crm")
    assert plugin is not None
    assert plugin.source == "extension"
    assert plugin.enabled is False
    assert plugin.package == "example-plugin"
    assert loaded is False
