from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.connectors.store import KnowledgeStore
from openjarvis.server.dashboard import dashboard_router


def test_dashboard_calendar_reads_minimal_upcoming_events(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()

    with KnowledgeStore() as store:
        for source, title, start, metadata, chunk in [
            ("gcalendar", "Upcoming all day", today, {"all_day_date": today}, 0),
            ("gcalendar", "Upcoming timed", now + timedelta(hours=2), {}, 0),
            ("gcalendar", "Upcoming timed", now + timedelta(hours=2), {}, 1),
            ("gcalendar", "Already started", now - timedelta(hours=2), {}, 0),
            ("other", "Other source", now + timedelta(hours=4), {}, 0),
        ]:
            store.store(
                "private meeting notes", source=source, doc_type="event",
                doc_id=title, title=title, timestamp=start, metadata=metadata,
                chunk_index=chunk, participants=["secret@example.com"],
            )

    app = FastAPI()
    app.include_router(dashboard_router)
    with TestClient(app) as client:
        response = client.get("/v1/dashboard/calendar", params={"local_day": today})

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    events = response.json()["events"]
    assert [event["title"] for event in events] == [
        "Upcoming all day", "Upcoming timed"
    ]
    assert events[0]["all_day_date"] == today
    assert events[1]["all_day_date"] is None
    assert "private meeting notes" not in response.text
    assert "secret@example.com" not in response.text
