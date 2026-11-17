"""Tests for workflow engine (Phase 15.1)."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from openjarvis.core.events import EventBus, EventType
from openjarvis.workflow.builder import WorkflowBuilder
from openjarvis.workflow.engine import WorkflowEngine
from openjarvis.workflow.graph import WorkflowGraph
from openjarvis.workflow.serialization import graph_from_dict
from openjarvis.workflow.types import NodeType, WorkflowEdge, WorkflowNode


class TestWorkflowGraph:
    def test_import_rejects_reserved_input_node(self):
        with pytest.raises(ValueError, match="reserved for the workflow input"):
            graph_from_dict({"nodes": [{"id": "_input", "type": "transform"}]})

    @pytest.mark.parametrize("count", [0, -1, 1.5, True, None])
    def test_rejects_invalid_loop_count_in_serialized_graph(self, count):
        with pytest.raises(ValueError, match="positive integer max_iterations"):
            graph_from_dict({
                "nodes": [{"id": "review", "type": "loop", "max_iterations": count}],
            })

    def test_add_node(self):
        g = WorkflowGraph("test")
        g.add_node(WorkflowNode(id="a", node_type=NodeType.AGENT))
        assert g.get_node("a") is not None
        assert len(g.nodes) == 1

    def test_add_duplicate_node_raises(self):
        g = WorkflowGraph("test")
        g.add_node(WorkflowNode(id="a", node_type=NodeType.AGENT))
        with pytest.raises(ValueError, match="Duplicate"):
            g.add_node(WorkflowNode(id="a", node_type=NodeType.AGENT))

    def test_add_edge(self):
        g = WorkflowGraph("test")
        g.add_node(WorkflowNode(id="a", node_type=NodeType.AGENT))
        g.add_node(WorkflowNode(id="b", node_type=NodeType.AGENT))
        g.add_edge(WorkflowEdge(source="a", target="b"))
        assert len(g.edges) == 1

    def test_add_edge_missing_source_raises(self):
        g = WorkflowGraph("test")
        g.add_node(WorkflowNode(id="b", node_type=NodeType.AGENT))
        with pytest.raises(ValueError, match="Source"):
            g.add_edge(WorkflowEdge(source="a", target="b"))

    def test_validate_acyclic(self):
        g = WorkflowGraph("test")
        g.add_node(WorkflowNode(id="a", node_type=NodeType.AGENT))
        g.add_node(WorkflowNode(id="b", node_type=NodeType.AGENT))
        g.add_edge(WorkflowEdge(source="a", target="b"))
        valid, msg = g.validate()
        assert valid

    def test_validate_cyclic(self):
        g = WorkflowGraph("test")
        g.add_node(WorkflowNode(id="a", node_type=NodeType.AGENT))
        g.add_node(WorkflowNode(id="b", node_type=NodeType.AGENT))
        g.add_edge(WorkflowEdge(source="a", target="b"))
        g.add_edge(WorkflowEdge(source="b", target="a"))
        valid, msg = g.validate()
        assert not valid
        assert "Cycle" in msg

    def test_topological_sort(self):
        g = WorkflowGraph("test")
        g.add_node(WorkflowNode(id="a", node_type=NodeType.AGENT))
        g.add_node(WorkflowNode(id="b", node_type=NodeType.AGENT))
        g.add_node(WorkflowNode(id="c", node_type=NodeType.AGENT))
        g.add_edge(WorkflowEdge(source="a", target="b"))
        g.add_edge(WorkflowEdge(source="b", target="c"))
        order = g.topological_sort()
        assert order.index("a") < order.index("b")
        assert order.index("b") < order.index("c")

    def test_execution_stages(self):
        g = WorkflowGraph("test")
        g.add_node(WorkflowNode(id="a", node_type=NodeType.AGENT))
        g.add_node(WorkflowNode(id="b", node_type=NodeType.AGENT))
        g.add_node(WorkflowNode(id="c", node_type=NodeType.AGENT))
        g.add_edge(WorkflowEdge(source="a", target="c"))
        g.add_edge(WorkflowEdge(source="b", target="c"))
        stages = g.execution_stages()
        # a and b can run in parallel (stage 1), c after (stage 2)
        assert len(stages) == 2
        assert set(stages[0]) == {"a", "b"}
        assert stages[1] == ["c"]

    def test_predecessors_successors(self):
        g = WorkflowGraph("test")
        g.add_node(WorkflowNode(id="a", node_type=NodeType.AGENT))
        g.add_node(WorkflowNode(id="b", node_type=NodeType.AGENT))
        g.add_edge(WorkflowEdge(source="a", target="b"))
        assert g.predecessors("b") == ["a"]
        assert g.successors("a") == ["b"]


class TestWorkflowBuilder:
    def test_build_simple(self):
        wf = (
            WorkflowBuilder("test")
            .add_agent("a", agent="simple")
            .add_agent("b", agent="simple")
            .connect("a", "b")
            .build()
        )
        assert wf.name == "test"
        assert len(wf.nodes) == 2
        assert len(wf.edges) == 1

    def test_sequential(self):
        wf = (
            WorkflowBuilder("seq")
            .add_agent("a", agent="simple")
            .add_agent("b", agent="simple")
            .add_agent("c", agent="simple")
            .sequential("a", "b", "c")
            .build()
        )
        assert len(wf.edges) == 2

    def test_build_cyclic_raises(self):
        with pytest.raises(ValueError, match="Invalid"):
            (
                WorkflowBuilder("bad")
                .add_agent("a", agent="simple")
                .add_agent("b", agent="simple")
                .connect("a", "b")
                .connect("b", "a")
                .build()
            )


class TestWorkflowEngine:
    def test_n8n_documentation_step_uses_only_node_search(self):
        from types import SimpleNamespace

        from openjarvis.core.types import ToolResult
        from openjarvis.tools._stubs import ToolSpec

        search = Mock()
        search.spec = ToolSpec(name="search_nodes", description="Node documentation")
        search.server_name = "n8n-mcp"
        search.execute.return_value = ToolResult(
            tool_name="search_nodes", content="Schedule Trigger", success=True
        )
        unrelated = Mock()
        unrelated.spec.name = "search_nodes"
        unrelated.server_name = "unrelated-mcp"
        graph = graph_from_dict({
            "nodes": [{"id": "lookup", "type": "tool", "config": {
                "tool_name": "n8n_node_lookup",
                "tool_args": '{"query":"ignored","limit":999}',
            }}],
        })
        engine = WorkflowEngine()
        result = engine.run(
            graph, SimpleNamespace(mcp_tools=[unrelated, search]),
            initial_input="  schedule trigger  ",
        )
        assert result.success
        assert result.final_output == "Schedule Trigger"
        assert result.steps[0].metadata["mcp_server"] == "n8n-mcp"
        search.execute.assert_called_once_with(query="schedule trigger", limit=5)
        unrelated.execute.assert_not_called()

        unavailable = engine.run(graph, initial_input="schedule trigger")
        assert not unavailable.success
        assert "Configure exactly one n8n-mcp server" in unavailable.steps[0].output

        ambiguous = engine.run(
            graph, SimpleNamespace(mcp_tools=[search, search]),
            initial_input="schedule trigger",
        )
        assert not ambiguous.success
        assert search.execute.call_count == 1

    def test_run_invalid_graph(self):
        engine = WorkflowEngine()
        g = WorkflowGraph("bad")
        g.add_node(WorkflowNode(id="a", node_type=NodeType.AGENT))
        g.add_node(WorkflowNode(id="b", node_type=NodeType.AGENT))
        g.add_edge(WorkflowEdge(source="a", target="b"))
        g.add_edge(WorkflowEdge(source="b", target="a"))
        result = engine.run(g)
        assert not result.success

    def test_run_transform_node(self):
        bus = EventBus(record_history=True)
        engine = WorkflowEngine(bus=bus)
        wf = WorkflowBuilder("test").add_transform("t", transform="concatenate").build()
        result = engine.run(wf, initial_input="hello")
        assert result.success
        assert result.final_output == "hello"

    def test_resume_output_cannot_replace_original_workflow_input(self):
        graph = WorkflowBuilder("input").add_transform("result").build()
        result = WorkflowEngine().run(
            graph, initial_input="original", resume_outputs={"_input": "replaced"}
        )
        assert result.final_output == "original"

    def test_transform_only_reads_connected_predecessor(self):
        graph = (
            WorkflowBuilder("test")
            .add_transform("connected", transform="first_line")
            .add_transform("unconnected", transform="concatenate")
            .add_transform("result", transform="concatenate")
            .connect("connected", "result")
            .build()
        )
        result = WorkflowEngine().run(graph, initial_input="first\nsecond")
        assert result.final_output == "first"

    def test_events_emitted(self):
        bus = EventBus(record_history=True)
        engine = WorkflowEngine(bus=bus)
        wf = WorkflowBuilder("test").add_transform("t", transform="concatenate").build()
        engine.run(wf, initial_input="hello")
        event_types = {e.event_type for e in bus.history}
        assert EventType.WORKFLOW_START in event_types
        assert EventType.WORKFLOW_END in event_types

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ('{"value":"lead@example.com"}', "lead@example.com"),
            ('{"value":false}', "false"),
            ('{"value":null}', "null"),
            ('{"value":[1,2]}', "[1, 2]"),
            ('{"other":1}', None),
            ("[1,2]", None),
            ("malformed", None),
        ],
    )
    def test_extract_json_field_from_connected_output(self, source, expected):
        graph = (
            WorkflowBuilder("extract")
            .add_transform("record", transform="first_line")
            .add_transform("field", transform="json_field:value")
            .connect("record", "field")
            .build()
        )
        result = WorkflowEngine().run(graph, initial_input=f"{source}\ntrailing text")
        if expected is None:
            assert result.status == "failed"
            assert "JSON field extraction failed" in result.final_output
        else:
            assert result.success
            assert result.final_output == expected

    @pytest.mark.parametrize("node_type", ["agent", "loop"])
    def test_connected_empty_field_does_not_pass_original_record(self, node_type):
        builder = WorkflowBuilder("empty field").add_transform(
            "field", transform="json_field:note"
        )
        if node_type == "agent":
            builder.add_agent("review")
        else:
            builder.add_loop("review", max_iterations=1)
        graph = builder.connect("field", "review").build()
        system = Mock()
        system.ask.return_value = {"content": "reviewed"}
        result = WorkflowEngine().run(
            graph, system=system, initial_input='{"note":"","private":"internal"}'
        )
        assert result.success
        system.ask.assert_called_once()
        assert system.ask.call_args.args == ("",)

    def test_model_step_uses_only_connected_input_and_reports_model_failure(self):
        graph = (
            WorkflowBuilder("model response")
            .add_transform("field", transform="json_field:note")
            .add_agent("model", agent="none")
            .connect("field", "model")
            .build()
        )
        system = Mock()
        system.ask.return_value = {"content": "Model unavailable", "error": True}
        result = WorkflowEngine().run(
            graph,
            system=system,
            initial_input='{"note":"summarize","private":"internal"}',
        )
        system.ask.assert_called_once_with(
            "summarize", agent="none", tools=None, context=False
        )
        assert result.status == "failed"
        assert result.final_output == "Model unavailable"

    @pytest.mark.parametrize("source", ["gmail", "gmail_imap"])
    def test_connector_search_filters_by_source(self, tmp_path, monkeypatch, source):
        from openjarvis.connectors.gmail_imap import GmailIMAPConnector
        from openjarvis.connectors.store import KnowledgeStore
        from openjarvis.core.registry import ConnectorRegistry

        if not ConnectorRegistry.contains("gmail_imap"):
            ConnectorRegistry.register_value("gmail_imap", GmailIMAPConnector)

        monkeypatch.setattr("openjarvis.core.config.DEFAULT_CONFIG_DIR", tmp_path)
        with KnowledgeStore() as store:
            store.store(content="Invoice safety deposit is 250", source="gmail")
            store.store(content="Invoice unrelated chat", source="slack")
        graph = graph_from_dict({
            "nodes": [{
                "id": "search",
                "type": "tool",
                "config": {
                    "tool_name": "knowledge_search",
                    "query_from_input": True,
                    "source": source,
                },
            }],
        })

        result = WorkflowEngine().run(graph, initial_input="invoice")

        assert result.status == "succeeded"
        assert "safety deposit is 250" in result.final_output
        assert "unrelated chat" not in result.final_output

    def test_connector_review_requires_evidence(self, tmp_path, monkeypatch):
        monkeypatch.setattr("openjarvis.core.config.DEFAULT_CONFIG_DIR", tmp_path)
        graph = graph_from_dict({
            "nodes": [
                {"id": "search", "type": "tool", "config": {
                    "tool_name": "knowledge_search",
                    "query_from_input": True,
                    "source": "upload",
                    "require_match": True,
                }},
                {"id": "review", "type": "approval"},
            ],
            "edges": [{"source": "search", "target": "review"}],
        })

        result = WorkflowEngine().run(graph, initial_input="unmatched document")

        assert result.status == "failed"
        assert [step.node_id for step in result.steps] == ["search"]
        assert result.final_output == "No relevant results found."

    @pytest.mark.parametrize("include_brief", [False, True])
    def test_model_step_can_read_latest_shared_brief(
        self, tmp_path, monkeypatch, include_brief
    ):
        from openjarvis.core.shared_brain import update_brief

        monkeypatch.setattr(
            "openjarvis.core.shared_brain.get_config_dir", lambda: tmp_path
        )
        original = update_brief("Previous coordination context", 0)
        latest = update_brief("Latest coordination context", original)
        graph = graph_from_dict({
            "nodes": [{
                "id": "draft",
                "type": "agent",
                "agent": "none",
                "config": {"use_shared_brain": include_brief},
            }],
        })
        system = Mock()
        system.ask.return_value = {"content": "Draft output"}
        result = WorkflowEngine().run(graph, system, initial_input="Exact input")

        assert result.status == "succeeded"
        prompt = system.ask.call_args.args[0]
        assert "Previous coordination context" not in prompt
        if include_brief:
            assert prompt.endswith("Workflow input:\nExact input")
            assert "Latest coordination context" in prompt
            assert result.steps[0].metadata["shared_brain_revision"] == latest
        else:
            assert prompt == "Exact input"
            assert "shared_brain_revision" not in result.steps[0].metadata

    def test_saved_model_instruction_is_separate_from_workflow_input(self):
        from openjarvis.core.config import JarvisConfig
        from openjarvis.core.types import Role
        from openjarvis.engine.multi import MultiEngine
        from openjarvis.system.core import JarvisSystem

        graph = graph_from_dict({
            "nodes": [{
                "id": "model",
                "type": "agent",
                "agent": "none",
                "config": {
                    "instruction": "Summarize the record.",
                    "model": "review-model",
                },
            }],
        })
        engine = Mock()
        engine.engine_id = "instrumented"
        engine.list_models.return_value = ["review-model"]
        engine.generate.return_value = {
            "content": "Summary",
            "model": "provider/model-v2",
        }
        multi = MultiEngine([("review-engine", engine)])
        system = JarvisSystem(JarvisConfig(), EventBus(), multi, "multi", "test")

        result = WorkflowEngine().run(graph, system, initial_input="Example record")

        assert result.final_output == "Summary"
        assert engine.generate.call_args.kwargs["model"] == "review-model"
        assert result.steps[0].metadata == {
            "model": "review-model",
            "resolved_model": "provider/model-v2",
            "engine": "multi",
            "resolved_engine": "review-engine",
        }
        assert system.model == "test"
        messages = engine.generate.call_args.args[0]
        assert [(message.role, message.content) for message in messages] == [
            (Role.SYSTEM, "Summarize the record."),
            (Role.USER, "Example record"),
        ]

    @pytest.mark.parametrize(
        ("model_result", "expected"),
        [
            ({"content": "  "}, "The model returned an empty response."),
            ({"content": "Backend unavailable", "error": True}, "Backend unavailable"),
            ({"error": "Engine connection closed"}, "Engine connection closed"),
        ],
    )
    def test_failed_model_output_does_not_reach_approval(self, model_result, expected):
        from openjarvis.core.config import JarvisConfig
        from openjarvis.system.core import JarvisSystem

        graph = (
            WorkflowBuilder("model review")
            .add_agent("model", agent="none")
            .add_approval(
                "review", action_type="review", description="Review model output"
            )
            .connect("model", "review")
            .build()
        )
        engine = Mock()
        engine.generate.return_value = model_result
        system = JarvisSystem(JarvisConfig(), EventBus(), engine, "test", "test")

        result = WorkflowEngine().run(graph, system, initial_input="Example record")

        assert result.status == "failed"
        assert result.final_output == expected
        assert [step.node_id for step in result.steps] == ["model"]

    def test_loop_without_backend_reports_no_iterations(self):
        graph = WorkflowBuilder("review").add_loop("review").build()
        result = WorkflowEngine().run(graph)
        assert result.status == "failed"
        assert result.steps[0].metadata["iterations"] == 0

    def test_keep_selected_json_fields(self):
        graph = (
            WorkflowBuilder("select")
            .add_transform("select", transform="json_select:email, qualified")
            .build()
        )
        engine = WorkflowEngine()
        result = engine.run(
            graph,
            initial_input='{"email":"lead@example.com","qualified":false,"notes":"private"}',
        )
        assert result.success
        assert json.loads(result.final_output) == {
            "email": "lead@example.com",
            "qualified": False,
        }
        assert engine.run(graph, initial_input='{"email":null}').status == "failed"

    def test_conditional_edges_skip_unselected_branch(self):
        graph = (
            WorkflowBuilder("conditional")
            .add_condition("check", expr="outputs['_input'] == 'yes'")
            .add_transform("accepted")
            .add_transform("rejected")
            .add_transform("rejected_followup")
            .add_transform("merge")
            .connect("check", "accepted", condition="true")
            .connect("check", "rejected", condition="false")
            .connect("rejected", "rejected_followup")
            .connect("accepted", "merge")
            .connect("rejected_followup", "merge")
            .build()
        )
        engine = WorkflowEngine()
        yes = engine.run(graph, initial_input="yes")
        assert yes.success
        assert [step.node_id for step in yes.steps] == ["check", "accepted", "merge"]
        no = engine.run(graph, initial_input="no")
        assert no.success
        assert [step.node_id for step in no.steps] == [
            "check",
            "rejected",
            "rejected_followup",
            "merge",
        ]

    def test_invalid_condition_does_not_run_false_branch(self):
        graph = (
            WorkflowBuilder("invalid condition")
            .add_condition("check", expr="outputs['missing']")
            .add_transform("fallback")
            .connect("check", "fallback", condition="false")
            .build()
        )
        result = WorkflowEngine().run(graph)
        assert result.status == "failed"
        assert [step.node_id for step in result.steps] == ["check"]
        assert "Condition evaluation failed" in result.final_output

    def test_parallel_failure_takes_precedence_over_pending_approval(self, tmp_path):
        from openjarvis.tools.approval_store import ApprovalStore

        graph = (
            WorkflowBuilder("parallel review")
            .add_approval("review", action_type="review", description="Review output")
            .add_condition("check", expr="outputs['missing']")
            .build()
        )
        approvals = ApprovalStore(str(tmp_path / "approvals.db"))
        try:
            result = WorkflowEngine(approval_store=approvals).run(graph)
        finally:
            approvals.close()

        assert {step.node_id for step in result.steps} == {"review", "check"}
        assert result.status == "failed"
        assert "Condition evaluation failed" in result.final_output
