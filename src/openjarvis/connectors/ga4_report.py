"""Read-only Google Analytics views for the Command Center dashboard."""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

import httpx

from openjarvis.connectors.google_auth import (
    GoogleAuthError,
    call_with_refresh,
    current_access_token,
)
from openjarvis.connectors.oauth import delete_tokens, save_tokens
from openjarvis.core.paths import get_config_dir
from openjarvis.security.file_utils import secure_write_json

_credential_lock = threading.Lock()


def _run_views_report(token: str, property_id: str) -> dict:
    response = httpx.post(
        f"https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "dateRanges": [{"startDate": "28daysAgo", "endDate": "yesterday"}],
            "metrics": [{"name": "screenPageViews"}],
        },
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()


def ga4_settings() -> dict:
    override = os.environ.get("OPENJARVIS_GA4_PROPERTY_ID", "").strip()
    if override:
        return {"property_id": override, "environment_override": True}
    try:
        settings = json.loads(
            (get_config_dir() / "ga4-settings.json").read_text(encoding="utf-8")
        )
        property_id = settings.get("property_id", "")
    except (OSError, ValueError, AttributeError):
        property_id = ""
    return {
        "property_id": property_id if isinstance(property_id, str) else "",
        "environment_override": False,
    }


def save_ga4_property(property_id: str) -> dict:
    property_id = property_id.strip()
    if property_id and not re.fullmatch(r"[0-9]{1,30}", property_id):
        raise ValueError("GA4 property ID must be numeric")
    if ga4_settings()["environment_override"]:
        raise ValueError("GA4 property is managed by the backend environment")
    secure_write_json(
        get_config_dir() / "ga4-settings.json", {"property_id": property_id}
    )
    return {"property_id": property_id, "environment_override": False}


def ga4_credentials_path() -> str:
    return str(get_config_dir() / "connectors" / "ga4.json")


def authorize_ga4(client_file: Path) -> None:
    """Authorize read-only Analytics using a Google Desktop OAuth client."""
    try:
        config = json.loads(client_file.read_text(encoding="utf-8"))
        client_id = config["installed"]["client_id"]
        client_secret = config["installed"]["client_secret"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError("Expected a Google Desktop OAuth client JSON file") from exc
    if (
        not isinstance(client_id, str)
        or not client_id.endswith(".apps.googleusercontent.com")
        or not isinstance(client_secret, str)
        or not client_secret
    ):
        raise ValueError("Expected a Google Desktop OAuth client ID and secret")

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(
        {"installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }},
        scopes=["https://www.googleapis.com/auth/analytics.readonly"],
        autogenerate_code_verifier=True,
    )
    try:
        credentials = flow.run_local_server(
            host="127.0.0.1", port=0, timeout_seconds=120, prompt="consent"
        )
    except Exception as exc:
        raise RuntimeError("Google Analytics authorization did not complete") from exc
    if not credentials.token or not credentials.refresh_token:
        raise ValueError("Google did not grant an offline Analytics authorization")
    save_tokens(ga4_credentials_path(), {
        "access_token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    })


def remove_ga4_authorization() -> None:
    with _credential_lock:
        delete_tokens(ga4_credentials_path())


def ga4_views() -> dict:
    property_id = ga4_settings()["property_id"]
    if not property_id:
        return {"status": "unconfigured", "views": None}
    if not re.fullmatch(r"[0-9]{1,30}", property_id):
        return {"status": "invalid_property", "views": None}
    with _credential_lock:
        credentials = ga4_credentials_path()
        try:
            token = current_access_token(credentials)
        except (AttributeError, UnicodeError):
            token = ""
        if not isinstance(token, str) or not token:
            return {"status": "authorization_required", "views": None}

        try:
            report = call_with_refresh(_run_views_report, credentials, property_id)
            headers = report["metricHeaders"]
            if headers[0]["name"] != "screenPageViews":
                raise ValueError("Unexpected GA4 metric")
            rows = report.get("rows", [])
            views = int(rows[0]["metricValues"][0]["value"]) if rows else 0
            if views < 0:
                raise ValueError("Invalid GA4 views count")
        except GoogleAuthError:
            return {"status": "authorization_required", "views": None}
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                return {"status": "authorization_required", "views": None}
            return {"status": "unavailable", "views": None}
        except (httpx.RequestError, KeyError, IndexError, TypeError, ValueError):
            return {"status": "unavailable", "views": None}
        return {"status": "live", "views": views}
