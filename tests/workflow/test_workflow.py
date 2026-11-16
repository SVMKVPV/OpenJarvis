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
