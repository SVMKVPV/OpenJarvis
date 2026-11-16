import time
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.server.app import create_app  # noqa: E402


def test_social_draft_review_planning_persists_and_checks_revision(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "openjarvis.server.social_content_routes.get_config_dir", lambda: tmp_path
    )
    fields = {
        "title": "Spring launch",
        "caption": "Initial caption",
        "channels": ["instagram", "linkedin"],
    }
    headers = {"Authorization": "Bearer test-content-key"}
    base = "/v1/social-content/drafts"
    summary_path = "/v1/social-content/summary"

    def session():
        return TestClient(create_app(MagicMock(), "test", api_key="test-content-key"))

    with session() as client:
        assert client.get(base).status_code == 401
        assert client.get(summary_path).status_code == 401
        assert client.get(summary_path, headers=headers).json() == {
            "review_count": 0,
            "items": [],
        }
        assert client.post(base, json=fields).status_code == 401
        new = client.post(base, json=fields, headers=headers)
        assert new.status_code == 201
        draft = new.json()
        assert draft["state"] == "draft" and draft["revision"] == 1
        path = f"{base}/{draft['id']}"

        def decide(action, revision, **options):
            return client.post(
                path + "/actions",
                headers=headers,
                json={
                    "action": action,
                    "revision": revision,
                    **options,
                },
            )

        assert decide("approve", 1).status_code == 409
        revised = client.put(
            path,
            headers=headers,
            json={
                **fields,
                "caption": "Edited caption",
                "revision": 1,
            },
        )
        assert revised.status_code == 200
        pending = decide("submit_review", 2)
        assert pending.status_code == 200 and pending.json()["state"] == "review"
        summary = client.get(summary_path, headers=headers)
        assert summary.headers["Cache-Control"] == "no-store"
        assert summary.json() == {
            "review_count": 1,
            "items": [{
                "id": draft["id"],
                "title": fields["title"],
                "channels": fields["channels"],
                "state": "review",
                "scheduled_at": None,
                "publications": [],
            }],
        }
        assert decide("approve", 2).status_code == 409
        accepted = decide("approve", 3)
        assert accepted.status_code == 200 and accepted.json()["state"] == "approved"
        start = time.time() + 7200
        assert decide("plan", 4, scheduled_at=time.time() - 1).status_code == 422
        planned = decide("plan", 4, scheduled_at=start)
        assert planned.status_code == 200 and planned.json()["state"] == "planned"

    with session() as restarted:
        listed = restarted.get(base, headers=headers)
        assert listed.status_code == 200
        assert listed.headers["Cache-Control"] == "no-store"
        (item,) = listed.json()["drafts"]
        assert item["id"] == draft["id"]
        assert item["caption"] == "Edited caption"
        assert item["state"] == "planned" and item["scheduled_at"] == start
        summary = restarted.get(summary_path, headers=headers).json()
        assert summary["review_count"] == 0
        assert summary["items"][0]["scheduled_at"] == start
        returned = restarted.post(
            path + "/actions",
            headers=headers,
            json={
                "action": "return_to_draft",
                "revision": item["revision"],
            },
        )
        assert returned.status_code == 200
        assert returned.json()["state"] == "draft"
        assert returned.json()["scheduled_at"] is None
        publication_path = path + "/publications"
        record = {
            "channel": "instagram", "url": "https://www.instagram.com/p/example/",
            "posted_at": time.time() - 60, "revision": returned.json()["revision"],
        }
        assert restarted.post(
            publication_path, headers=headers, json=record
        ).status_code == 409
        for action in ("submit_review", "approve"):
            result = restarted.post(path + "/actions", headers=headers, json={
                "action": action, "revision": record["revision"],
            })
            assert result.status_code == 200
            record["revision"] = result.json()["revision"]
        assert restarted.post(publication_path, headers=headers, json={
            **record, "url": "javascript:alert(1)",
        }).status_code == 422
        first = restarted.post(publication_path, headers=headers, json=record)
        assert first.status_code == 200 and first.json()["state"] == "approved"
        record["revision"] = first.json()["revision"]
        duplicate = restarted.post(publication_path, headers=headers, json=record)
        assert duplicate.status_code == 409
        assert restarted.post(path + "/actions", headers=headers, json={
            "action": "return_to_draft", "revision": record["revision"],
        }).status_code == 409
        final = restarted.post(publication_path, headers=headers, json={
            **record, "channel": "linkedin", "url": "https://www.linkedin.com/posts/example",
        })
        assert final.status_code == 200 and final.json()["state"] == "published"
        corrected = {
            **record,
            "url": "https://www.instagram.com/p/corrected/",
            "revision": final.json()["revision"],
        }
        revision_conflict = restarted.put(
            publication_path, headers=headers, json=record
        )
        assert revision_conflict.status_code == 409
        result = restarted.put(publication_path, headers=headers, json=corrected)
        assert result.status_code == 200 and result.json()["state"] == "published"
        assert result.json()["caption"] == "Edited caption"
        posted, = restarted.get(summary_path, headers=headers).json()["items"]
        assert {entry["channel"] for entry in posted["publications"]} == {
            "instagram", "linkedin",
        }
        assert corrected["url"] in {entry["url"] for entry in posted["publications"]}
