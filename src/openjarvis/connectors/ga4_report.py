"""Read-only Google Analytics views for the Command Center dashboard."""

from __future__ import annotations

import os
import re

import httpx

from openjarvis.connectors.google_auth import (
    GoogleAuthError,
    call_with_refresh,
    current_access_token,
)
from openjarvis.core.paths import get_config_dir


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


def ga4_views() -> dict:
    property_id = os.environ.get("OPENJARVIS_GA4_PROPERTY_ID", "").strip()
    if not property_id:
        return {"status": "unconfigured", "views": None}
    if not re.fullmatch(r"[0-9]{1,30}", property_id):
        return {"status": "invalid_property", "views": None}
    credentials = str(get_config_dir() / "connectors" / "ga4.json")
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
