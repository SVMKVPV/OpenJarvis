"""Stable JSON representation for persisted workflow graphs."""

from __future__ import annotations

from typing import Any, Mapping

from openjarvis.workflow.graph import WorkflowGraph
from openjarvis.workflow.types import NodeType, WorkflowEdge, WorkflowNode


def graph_to_dict(graph: WorkflowGraph) -> dict[str, Any]:
    return {
        "name": graph.name,
        "nodes": [
            {
                "id": node.id,
                "type": node.node_type.value,
                "agent": node.agent,
                "tools": list(node.tools),
                "config": dict(node.config),
                "condition_expr": node.condition_expr,
                "max_iterations": node.max_iterations,
                "transform_expr": node.transform_expr,
            }
            for node in graph.nodes
        ],
        "edges": [
            {
                "source": edge.source,
                "target": edge.target,
                "condition": edge.condition,
            }
            for edge in graph.edges
        ],
    }


def graph_from_dict(data: Mapping[str, Any]) -> WorkflowGraph:
    graph = WorkflowGraph(name=str(data.get("name", "workflow")))
    for raw in data.get("nodes", []):
        node_type = NodeType(str(raw.get("type", "agent")))
        max_iterations = raw.get("max_iterations", 10)
        if node_type != NodeType.LOOP or isinstance(max_iterations, str):
            max_iterations = int(max_iterations)
        graph.add_node(
            WorkflowNode(
                id=str(raw["id"]),
                node_type=node_type,
                agent=str(raw.get("agent", "")),
                tools=[str(item) for item in raw.get("tools", [])],
                config=dict(raw.get("config", {})),
                condition_expr=str(raw.get("condition_expr", "")),
                max_iterations=max_iterations,
                transform_expr=str(raw.get("transform_expr", "")),
            )
        )
    for raw in data.get("edges", []):
        graph.add_edge(
            WorkflowEdge(
                source=str(raw["source"]),
                target=str(raw["target"]),
                condition=str(raw.get("condition", "")),
            )
        )
    valid, message = graph.validate()
    if not valid:
        raise ValueError(f"Invalid workflow graph: {message}")
    if not graph.nodes:
        raise ValueError("Workflow graph must contain at least one node")
    return graph


__all__ = ["graph_from_dict", "graph_to_dict"]
