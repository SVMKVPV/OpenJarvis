from fastapi import FastAPI
from fastapi.testclient import TestClient

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
                    thread_id=thread,
                    channel=channel,
                    timestamp=f"2026-11-0{day}T00:00:00+00:00",
                    chunk_index=chunk,
                )
        response = client.get(route)
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert response.json() == {"threads_to_review": 1}
