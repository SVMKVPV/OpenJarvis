"""Tests for MonitorOperativeAgent."""

from unittest.mock import MagicMock, patch

from openjarvis.agents.monitor_operative import MonitorOperativeAgent
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools.knowledge_search import KnowledgeSearchTool


def _make_engine(content: str = "Hello") -> MagicMock:
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.return_value = {
        "content": content,
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "model": "test-model",
        "finish_reason": "stop",
    }
    return engine


class TestMonitorOperativeAgent:
    def test_registration(self) -> None:
        # Import triggers registration; re-register after autouse fixture
        # clears the registry (same pattern as test_monitor.py)
        import openjarvis.agents.monitor_operative  # noqa: F401

        if not AgentRegistry.contains("monitor_operative"):
            AgentRegistry.register_value("monitor_operative", MonitorOperativeAgent)
        assert AgentRegistry.contains("monitor_operative")
        cls = AgentRegistry.get("monitor_operative")
        assert cls is MonitorOperativeAgent

    def test_instantiation(self) -> None:
        engine = _make_engine()
        agent = MonitorOperativeAgent(engine, "test-model")
        assert agent.agent_id == "monitor_operative"
        assert agent.accepts_tools is True

    def test_default_strategies(self) -> None:
        engine = _make_engine()
        agent = MonitorOperativeAgent(engine, "test-model")
        assert agent._memory_extraction == "causality_graph"
        assert agent._observation_compression == "summarize"
        assert agent._retrieval_strategy == "hybrid_with_self_eval"
        assert agent._task_decomposition == "phased"

    def test_custom_strategies(self) -> None:
        engine = _make_engine()
        agent = MonitorOperativeAgent(
            engine,
            "test-model",
            memory_extraction="scratchpad",
            observation_compression="none",
            retrieval_strategy="keyword",
            task_decomposition="monolithic",
        )
        assert agent._memory_extraction == "scratchpad"
        assert agent._observation_compression == "none"

    def test_simple_run(self) -> None:
        engine = _make_engine("The answer is 42.")
        agent = MonitorOperativeAgent(engine, "test-model")
        result = agent.run("What is the answer?")
        assert result.content == "The answer is 42."
        assert result.turns >= 1

    def test_blank_result_does_not_replace_persisted_state(self) -> None:
        memory = MagicMock()
        agent = MonitorOperativeAgent(
            _make_engine(),
            "test-model",
            operator_id="watcher",
            memory_backend=memory,
        )

        agent._auto_persist_state(" \n\t")

        memory.store.assert_not_called()

    def test_recovers_plain_json_knowledge_search_when_configured(self) -> None:
        call = '{"name":"knowledge_search","arguments":{"query":"Acacia","top_k":1}}'
        engine = _make_engine()
        engine.generate.side_effect = [
            {"content": call},
            {"content": "Invoice FIN-742"},
        ]
        tool = KnowledgeSearchTool()
        agent = MonitorOperativeAgent(engine, "test-model", tools=[tool])
        with patch.object(
            tool, "execute", return_value=ToolResult("knowledge_search", "FIN-742")
        ) as search:
            assert agent.run("Find the invoice.").content == "Invoice FIN-742"
        search.assert_called_once_with(query="Acacia", top_k=1)
        assert "tools" in engine.generate.call_args_list[0].kwargs
        assert not engine.generate.call_args_list[1].kwargs.get("tools")

        unconfigured = MonitorOperativeAgent(_make_engine(call), "test-model")
        assert unconfigured.run("Show a JSON example.").content == call

    def test_repeated_json_search_is_not_saved_as_the_answer(self) -> None:
        call = '{"name":"knowledge_search","arguments":{"query":"Acacia"}}'
        tool = KnowledgeSearchTool()
        agent = MonitorOperativeAgent(_make_engine(call), "test-model", tools=[tool])
        with patch.object(
            tool, "execute", return_value=ToolResult("knowledge_search", "FIN-742")
        ) as search:
            result = agent.run("Find the invoice.")
        assert "did not provide an answer" in result.content
        search.assert_called_once_with(query="Acacia")

    def test_empty_json_search_can_retry_before_final_answer(self) -> None:
        engine = _make_engine()
        engine.generate.side_effect = [
            {"content": '{"name":"knowledge_search","arguments":'
             '{"query":"Acacia","doc_type":"invoice"}}'},
            {"content": '{"name":"knowledge_search","arguments":{"query":"Acacia"}}'},
            {"content": "Invoice FIN-742"},
        ]
        tool = KnowledgeSearchTool()
        agent = MonitorOperativeAgent(engine, "test-model", tools=[tool])
        with patch.object(tool, "execute", side_effect=[
            ToolResult("knowledge_search", "No results", metadata={"num_results": 0}),
            ToolResult("knowledge_search", "FIN-742", metadata={"num_results": 1}),
        ]) as search:
            assert agent.run("Find the invoice.").content == "Invoice FIN-742"
        assert search.call_count == 2
        assert "tools" in engine.generate.call_args_list[1].kwargs
        assert "tools" not in engine.generate.call_args_list[2].kwargs

    def test_markdown_next_action_is_not_a_tool_call(self) -> None:
        brief = "**Current Owner:** Lina\n**Next Action:** Confirm the design."
        engine = _make_engine(brief)
        agent = MonitorOperativeAgent(
            engine, "test-model", tools=[KnowledgeSearchTool()]
        )
        assert agent.run("Write a delivery brief.").content == brief
        engine.generate.assert_called_once()

    def test_standalone_action_directive_remains_supported(self) -> None:
        directive = 'Action: knowledge_search\nAction Input: {"query":"design"}'
        assert MonitorOperativeAgent._extract_tool_call(directive) == (
            "knowledge_search",
            '{"query":"design"}',
        )
