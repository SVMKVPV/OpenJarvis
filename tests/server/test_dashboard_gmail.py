import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.agents.manager import AgentManager
from openjarvis.agents.tool_resolver import resolve_agent_tools
from openjarvis.connectors.store import KnowledgeStore
from openjarvis.server.dashboard import dashboard_router


def test_gmail_review_counts_threads_with_inbound_latest_message(tmp_path, monkeypatch):
    monkeypatch.setattr("openjarvis.core.config.DEFAULT_CONFIG_DIR", tmp_path)
    app = FastAPI()
    app.include_router(dashboard_router)
    route = "/v1/dashboard/gmail-review"
    with TestClient(app) as client:
        assert client.get(route).json() == {"threads_to_review": None}
        with KnowledgeStore() as store:
            for i, (thread, channel, day, chunk) in enumerate([
                ("unanswered", "INBOX", 1, 0),
                ("unanswered", "INBOX", 2, 0),
                ("unanswered", "INBOX", 2, 1),
                ("unanswered", "DRAFT", 3, 0),
                ("answered", "INBOX", 1, 0),
                ("answered", "SENT", 2, 0),
                ("unknown", None, 1, 0),
                ("", "INBOX", 1, 0),
            ]):
                store.store(
                    "private message body",
                    source="gmail",
                    doc_type="email",
                    doc_id=f"gmail:{i}",
                    source_id=f"a{i}",
                    title=f"Test subject {i}",
                    author="sender@example.test",
                    thread_id=thread,
                    channel=channel,
                    timestamp=f"2026-11-0{day}T00:00:00+00:00",
                    chunk_index=chunk,
                )
        response = client.get(route)
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert response.json() == {"threads_to_review": 1}
        candidates = client.get(route + "/candidates")
        assert candidates.headers["Cache-Control"] == "no-store"
        assert candidates.json() == {"candidates": [{
            "id": "gmail:1",
            "message_id": "a1",
            "subject": "Test subject 1",
            "sender": "sender@example.test",
            "received_at": "2026-11-02T00:00:00+00:00",
        }]}

        manager = AgentManager(str(tmp_path / "agents.db"))
        try:
            agent = manager.create_from_template("email_briefing", "Email Reply")
            with resolve_agent_tools(agent, engine=object(), model="local") as tools:
                result = tools.by_name["gmail_review_candidates"].execute()
            assert result.success
            assert json.loads(result.content) == candidates.json()["candidates"]
        finally:
            manager.close()

def test_finance_can_find_an_older_indexed_message_without_returning_its_body(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("openjarvis.core.config.DEFAULT_CONFIG_DIR", tmp_path)
    with KnowledgeStore() as store:
        for chunk in range(2):
            store.store(
                "Northwind Invoice M-42 with private line items",
                source="gmail", source_id="abc123", doc_id="gmail:abc123",
                doc_type="email", title="Northwind billing",
                author="vendor@example.test", channel="INBOX",
                timestamp="2026-07-01T10:00:00+00:00", chunk_index=chunk,
            )
        store.store(
            "Northwind Invoice M-42 newer draft",
            source="gmail", source_id="abc124", doc_id="gmail:abc124",
            doc_type="email", channel="DRAFT", timestamp="2026-11-01T00:00:00+00:00",
        )
        store.store(
            "Northwind Invoice M-42 in a different data source", source="upload",
            doc_id="gmail:abc125", source_id="abc125", doc_type="email",
        )
    app = FastAPI()
    app.include_router(dashboard_router)
    with TestClient(app) as client:
        response = client.post(
            "/v1/dashboard/gmail-evidence/search", json={"query": "Northwind M-42"}
        )
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert response.json() == {"candidates": [{
            "id": "gmail:abc123", "message_id": "abc123",
            "subject": "Northwind billing",
            "sender": "vendor@example.test", "received_at": "2026-07-01T10:00:00+00:00",
        }]}


def test_exact_gmail_reference_excludes_other_messages_and_attachments(tmp_path):
    with KnowledgeStore(tmp_path / "knowledge.db") as store:
        for reference, source_id, body, chunk in [
            ("gmail:abc", "abc", "Original email", 0),
            ("gmail:abc", "abc", "Second excerpt", 1),
            ("gmail:abc", "abc:attachment", "Attachment payload", 0),
            ("gmail:def", "def", "Other sender", 0),
        ]:
            store.store(
                body, source="gmail", doc_type="email", doc_id=reference,
                source_id=source_id, title="Same subject", chunk_index=chunk,
            )
        message = store.gmail_indexed_message("gmail:abc")
        assert message is not None
        assert message["excerpts"] == ["Original email", "Second excerpt"]
        assert store.gmail_indexed_message("gmail:unknown") is None
