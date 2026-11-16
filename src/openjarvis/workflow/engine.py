"""WorkflowEngine — executes a WorkflowGraph against a JarvisSystem."""

from __future__ import annotations

import concurrent.futures
import json
import time
from typing import Any, Callable, Dict, List, Optional

from openjarvis.core.events import EventBus, EventType
from openjarvis.workflow.graph import WorkflowGraph
from openjarvis.workflow.types import (
    NodeType,
    WorkflowNode,
    WorkflowResult,
    WorkflowStepResult,
)


class WorkflowEngine:
    """Execute DAG-based workflows.

    Sequential nodes run in topological order. Parallel-eligible nodes
    (same execution stage, no inter-dependencies) run via ThreadPoolExecutor.
    Condition nodes evaluate expressions against prior step outputs.
    Loop nodes use LoopGuard from Phase 14.3.
    """

    def __init__(
        self,
        *,
        bus: Optional[EventBus] = None,
        max_parallel: int = 4,
        default_node_timeout: int = 300,
        approval_store: Any = None,
    ) -> None:
        self._bus = bus
        self._max_parallel = max_parallel
        self._default_node_timeout = default_node_timeout
        self._approval_store = approval_store

    def run(
        self,
        graph: WorkflowGraph,
        system: Any = None,  # JarvisSystem
        *,
        initial_input: str = "",
        context: Optional[Dict[str, Any]] = None,
        step_callback: Optional[Callable[[WorkflowStepResult], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        resume_outputs: Optional[Dict[str, str]] = None,
        completed_nodes: Optional[set[str]] = None,
    ) -> WorkflowResult:
        """Execute a workflow graph end-to-end."""
        valid, msg = graph.validate()
        if not valid:
            return WorkflowResult(
                workflow_name=graph.name,
                success=False,
                status="failed",
                final_output=f"Invalid workflow: {msg}",
            )

        t0 = time.time()
        if self._bus:
            self._bus.publish(
                EventType.WORKFLOW_START,
                {"workflow": graph.name},
            )

        # State: outputs keyed by node_id
        outputs: Dict[str, str] = {"_input": initial_input, **(resume_outputs or {})}
        # Keep the caller's mutable context so durable runtimes can persist
        # approval IDs and other checkpoint state created during execution.
        ctx = context if context is not None else {}
        completed = set(completed_nodes or ())
        all_steps: List[WorkflowStepResult] = []
        success = True
        cancelled = False
        waiting_approval = False

        stages = graph.execution_stages()
        for stage in stages:
            stage = [
                node_id
                for node_id in stage
                if node_id not in completed
                and (
                    not graph.predecessors(node_id)
                    or graph.active_predecessors(node_id, outputs)
                )
            ]
            if not stage:
                continue
            if should_cancel and should_cancel():
                success = False
                cancelled = True
                break
            if len(stage) == 1:
                # Sequential execution
                step = self._execute_node(
                    graph.get_node(stage[0]),  # type: ignore[arg-type]
                    outputs,
                    ctx,
                    system,
                    graph,
                )
                all_steps.append(step)
                if step_callback:
                    step_callback(step)
                outputs[stage[0]] = step.output
                if step.metadata.get("workflow_status") == "waiting_approval":
                    waiting_approval = True
                    success = False
                    break
                if not step.success:
                    success = False
                    break
            else:
                # Parallel execution
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=min(len(stage), self._max_parallel),
                ) as pool:
                    futures = {
                        pool.submit(
                            self._execute_node,
                            graph.get_node(nid),
                            dict(outputs),
                            {
                                **ctx,
                                "_workflow_approvals": dict(
                                    ctx.get("_workflow_approvals", {})
                                ),
                            },
                            system,
                            graph,
                        ): nid
                        for nid in stage
                    }
                    for future in concurrent.futures.as_completed(futures):
                        nid = futures[future]
                        try:
                            step = future.result(
                                timeout=self._default_node_timeout,
                            )
                        except Exception as exc:
                            step = WorkflowStepResult(
                                node_id=nid,
                                success=False,
                                output=f"Node execution error: {exc}",
                            )
                        all_steps.append(step)
                        if step_callback:
                            step_callback(step)
                        outputs[nid] = step.output
                        if step.metadata.get("workflow_status") == "waiting_approval":
                            waiting_approval = True
                            success = False
                        if not step.success:
                            success = False

            if not success:
                break

        total = time.time() - t0
        # Final output is the output of the last executed node
        final_output = all_steps[-1].output if all_steps else ""
        failed_step = next(
            (
                step
                for step in all_steps
                if not step.success
                and step.metadata.get("workflow_status") != "waiting_approval"
            ),
            None,
        )
        if failed_step is not None:
            waiting_approval = False
            final_output = failed_step.output

        if self._bus:
            self._bus.publish(
                EventType.WORKFLOW_END,
                {"workflow": graph.name, "success": success, "duration": total},
            )

        return WorkflowResult(
            workflow_name=graph.name,
            success=success,
            status=(
                "cancelled"
                if cancelled
                else (
                    "waiting_approval"
                    if waiting_approval
                    else ("succeeded" if success else "failed")
                )
            ),
            steps=all_steps,
            final_output=final_output,
            total_duration_seconds=total,
        )

    def _execute_node(
        self,
        node: WorkflowNode,
        outputs: Dict[str, str],
        ctx: Dict[str, Any],
        system: Any,
        graph: WorkflowGraph,
    ) -> WorkflowStepResult:
        """Execute a single workflow node."""
        if self._bus:
            self._bus.publish(
                EventType.WORKFLOW_NODE_START,
                {"node": node.id, "type": node.node_type.value},
            )

        t0 = time.time()
        try:
            if node.node_type == NodeType.AGENT:
                result = self._run_agent_node(node, outputs, system, graph)
            elif node.node_type == NodeType.TOOL:
                result = self._run_tool_node(node, outputs, system)
            elif node.node_type == NodeType.CONDITION:
                result = self._run_condition_node(node, outputs)
            elif node.node_type == NodeType.TRANSFORM:
                result = self._run_transform_node(
                    node,
                    self._get_node_input(node, outputs, graph),
                )
            elif node.node_type == NodeType.LOOP:
                result = self._run_loop_node(node, outputs, system, graph)
            elif node.node_type == NodeType.APPROVAL:
                result = self._run_approval_node(
                    node,
                    ctx,
                    self._get_node_input(node, outputs, graph),
                )
            else:
                result = WorkflowStepResult(
                    node_id=node.id,
                    success=False,
                    output=f"Unknown node type: {node.node_type}",
                )
        except Exception as exc:
            result = WorkflowStepResult(
                node_id=node.id,
                success=False,
                output=f"Node error: {exc}",
            )

        result.duration_seconds = time.time() - t0

        if self._bus:
            self._bus.publish(
                EventType.WORKFLOW_NODE_END,
                {
                    "node": node.id,
                    "success": result.success,
                    "duration": result.duration_seconds,
                },
            )

        return result

    def _run_approval_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
        input_text: str,
    ) -> WorkflowStepResult:
        if self._approval_store is None:
            return WorkflowStepResult(
                node_id=node.id,
                success=False,
                output="Approval store is unavailable.",
            )

        from openjarvis.tools.approval_store import (
            STATUS_APPROVED,
            STATUS_DENIED,
            STATUS_EXPIRED,
        )

        approval_ids = context.setdefault("_workflow_approvals", {})
        approval_id = approval_ids.get(node.id)
        if approval_id:
            self._approval_store.expire_stale()
            action = self._approval_store.get_action(approval_id)
            if (
                action is None
                or action.payload.get("workflow_run_id")
                != context.get("_workflow_run_id", "")
                or action.payload.get("workflow_node_id") != node.id
            ):
                return WorkflowStepResult(
                    node_id=node.id,
                    success=False,
                    output="Approval record was not found.",
                )
            if action.status == STATUS_APPROVED:
                return WorkflowStepResult(
                    node_id=node.id,
                    output=input_text,
                    metadata={
                        "approval_id": approval_id,
                        "approval_status": "approved",
                    },
                )
            if action.status in {STATUS_DENIED, STATUS_EXPIRED}:
                return WorkflowStepResult(
                    node_id=node.id,
                    success=False,
                    output=f"Approval {action.status}",
                    metadata={
                        "approval_id": approval_id,
                        "approval_status": action.status,
                    },
                )
            return WorkflowStepResult(
                node_id=node.id,
                output="Waiting for approval",
                metadata={
                    "approval_id": approval_id,
                    "approval_status": action.status,
                    "workflow_status": "waiting_approval",
                },
            )

        payload = dict(node.config.get("payload", {}))
        payload["workflow_run_id"] = context.get("_workflow_run_id", "")
        payload["workflow_node_id"] = node.id
        action = self._approval_store.queue_action(
            action_type=str(node.config.get("action_type", "workflow_action")),
            description=str(node.config.get("description", "Approve workflow action")),
            payload=payload,
            permission_key=str(node.config.get("permission_key", node.id)),
            tier=str(node.config.get("tier", "high")),
            ttl_hours=int(node.config.get("ttl_hours", 24)),
        )
        approval_ids[node.id] = action.id
        return WorkflowStepResult(
            node_id=node.id,
            output="Waiting for approval",
            metadata={
                "approval_id": action.id,
                "approval_status": action.status,
                "workflow_status": "waiting_approval",
            },
        )

    def _get_node_input(
        self,
        node: WorkflowNode,
        outputs: Dict[str, str],
        graph: WorkflowGraph,
    ) -> str:
        """Get input for a node from predecessor outputs."""
        if graph.predecessors(node.id):
            return "\n\n".join(
                outputs[p]
                for p in graph.active_predecessors(node.id, outputs)
                if outputs[p]
            )
        return outputs.get("_input", "")

    def _run_agent_node(
        self,
        node: WorkflowNode,
        outputs: Dict[str, str],
        system: Any,
        graph: WorkflowGraph,
    ) -> WorkflowStepResult:
        """Execute an agent node."""
        input_text = self._get_node_input(node, outputs, graph)
        if system is None:
            return WorkflowStepResult(
                node_id=node.id,
                success=False,
                output="No system available for agent execution.",
            )
        try:
            instruction = (
                node.config.get("instruction", "") if node.agent == "none" else ""
            )
            result = system.ask(
                input_text,
                agent=node.agent or None,
                tools=node.tools or None,
                context=node.agent != "none",
                **({"system_prompt": instruction} if instruction else {}),
            )
            failed = bool(result.get("error"))
            return WorkflowStepResult(
                node_id=node.id,
                success=not failed,
                output=result.get("content") or (
                    "Model execution failed." if failed else ""
                ),
            )
        except Exception as exc:
            return WorkflowStepResult(
                node_id=node.id,
                success=False,
                output=f"Agent error: {exc}",
            )

    def _run_tool_node(
        self,
        node: WorkflowNode,
        outputs: Dict[str, str],
        system: Any,
    ) -> WorkflowStepResult:
        """Execute a tool node."""
        tool_name = node.config.get("tool_name", "")
        tool_args = node.config.get("tool_args", "{}")
        if system and system.tool_executor:
            from openjarvis.core.types import ToolCall

            tc = ToolCall(id=f"wf_{node.id}", name=tool_name, arguments=tool_args)
            tr = system.tool_executor.execute(tc)
            return WorkflowStepResult(
                node_id=node.id,
                success=tr.success,
                output=tr.content,
            )
        return WorkflowStepResult(
            node_id=node.id,
            success=False,
            output="No tool executor available.",
        )

    def _run_condition_node(
        self,
        node: WorkflowNode,
        outputs: Dict[str, str],
    ) -> WorkflowStepResult:
        """Evaluate a condition expression against outputs."""
        expr = node.condition_expr
        if not expr:
            return WorkflowStepResult(
                node_id=node.id,
                success=True,
                output="true",
            )
        # Simple expression evaluation — check if key exists and is truthy.
        # A bare eval() (even with empty __builtins__) is escapable via
        # attribute/subclass walks and allows unbounded-CPU expressions like
        # (9**9)**9. Use the shared allowlist AST interpreter instead: it has
        # no attribute access, no dunder names, and no reachable callables
        # beyond a fixed set of safe builtins, so escape vectors are
        # unreachable by construction. Evaluation errors stop the workflow.
        from openjarvis.tools.templates.loader import safe_eval_expr

        try:
            result = str(safe_eval_expr(expr, {"outputs": outputs}))
        except Exception:
            return WorkflowStepResult(
                node_id=node.id,
                success=False,
                output="Condition evaluation failed. Check the workflow expression.",
            )
        return WorkflowStepResult(
            node_id=node.id,
            success=True,
            output=result,
        )

    def _run_transform_node(
        self,
        node: WorkflowNode,
        combined: str,
    ) -> WorkflowStepResult:
        """Apply a transformation to the connected input."""
        expr = node.transform_expr
        if expr == "concatenate":
            return WorkflowStepResult(node_id=node.id, output=combined)
        if expr == "first_line":
            return WorkflowStepResult(
                node_id=node.id,
                output=combined.split("\n")[0] if combined else "",
            )
        operation, separator, field_names = expr.partition(":")
        if separator and operation in {"json_field", "json_select"}:
            try:
                data = json.loads(combined)
                if not isinstance(data, dict):
                    raise ValueError("Expected a JSON object")
                if operation == "json_field":
                    value = data[field_names]
                else:
                    keys = [key.strip() for key in field_names.split(",")]
                    if not all(keys):
                        raise ValueError("Expected a comma-separated list of fields")
                    value = {key: data[key] for key in keys}
                output = (
                    value
                    if isinstance(value, str)
                    else json.dumps(value, allow_nan=False)
                )
            except (KeyError, ValueError, RecursionError):
                return WorkflowStepResult(
                    node_id=node.id,
                    success=False,
                    output=(
                        "JSON field extraction failed. Check the input and field name."
                    ),
                )
            return WorkflowStepResult(node_id=node.id, output=output)
        return WorkflowStepResult(node_id=node.id, output=combined)

    def _run_loop_node(
        self,
        node: WorkflowNode,
        outputs: Dict[str, str],
        system: Any,
        graph: WorkflowGraph,
    ) -> WorkflowStepResult:
        """Execute a loop node (re-runs agent until condition or max iterations)."""
        if system is None:
            return WorkflowStepResult(
                node_id=node.id,
                success=False,
                output="No system available for loop execution.",
                metadata={"iterations": 0},
            )
        last_output = self._get_node_input(node, outputs, graph)
        exit_condition = node.condition_expr.lower()
        for iteration in range(1, node.max_iterations + 1):
            result = system.ask(last_output, agent=node.agent or None)
            last_output = result.get("content", "")
            if exit_condition and exit_condition in last_output.lower():
                break
        return WorkflowStepResult(
            node_id=node.id,
            success=True,
            output=last_output,
            metadata={"iterations": iteration},
        )


__all__ = ["WorkflowEngine"]
