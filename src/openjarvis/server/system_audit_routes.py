"""Read-only command-center security and operational audit."""

from __future__ import annotations

import os
import stat
from typing import Any

from fastapi import APIRouter, Request

from openjarvis.core.credentials import load_credentials
from openjarvis.core.paths import get_config_dir
from openjarvis.plugins import PluginCatalog

router = APIRouter(prefix="/v1/system", tags=["system-audit"])


def _finding(
    finding_id: str, severity: str, title: str, detail: str, **data: Any
) -> dict[str, Any]:
    return {
        "id": finding_id,
        "severity": severity,
        "title": title,
        "detail": detail,
        **data,
    }


@router.get("/audit")
async def system_audit(request: Request) -> dict[str, Any]:
    """Report risks without returning credential values or importing extensions."""
    findings: list[dict[str, Any]] = []
    auth_enabled = bool(getattr(request.app.state, "api_key", ""))
    findings.append(
        _finding(
            "api-authentication",
            "pass" if auth_enabled else "critical",
            "API authentication",
            "API key protection is enabled."
            if auth_enabled
            else "The local API has no API key protection configured.",
        )
    )

    plugins = PluginCatalog().list_plugins()
    extensions = [item for item in plugins if item.source == "extension"]
    enabled_extensions = [item for item in extensions if item.enabled]
    findings.append(
        _finding(
            "extension-code",
            "critical" if enabled_extensions else ("warning" if extensions else "pass"),
            "Third-party extension code",
            (
                f"{len(enabled_extensions)} third-party extensions are enabled."
                if enabled_extensions
                else (
                    f"{len(extensions)} installed extensions remain disabled "
                    "pending review."
                )
            ),
            installed=len(extensions),
            enabled=len(enabled_extensions),
        )
    )

    credential_path = get_config_dir() / "credentials.toml"
    credentials = load_credentials(path=credential_path)
    credential_count = sum(
        1 for values in credentials.values() for value in values.values() if value
    )
    credential_severity = "pass"
    credential_detail = (
        f"{credential_count} credential fields are stored; values are redacted."
    )
    if credential_path.exists() and os.name != "nt":
        mode = stat.S_IMODE(credential_path.stat().st_mode)
        if mode & 0o077:
            credential_severity = "critical"
            credential_detail = (
                "Credential file permissions are broader than owner-only."
            )
    findings.append(
        _finding(
            "credential-storage",
            credential_severity,
            "Credential storage",
            credential_detail,
            configured=credential_count,
        )
    )

    runtime = getattr(request.app.state, "workflow_runtime", None)
    run_counts: dict[str, int] = {}
    if runtime is not None:
        for run in runtime.store.list_runs(limit=200):
            status = run["status"]
            run_counts[status] = run_counts.get(status, 0) + 1
    unhealthy = run_counts.get("failed", 0) + run_counts.get("interrupted", 0)
    findings.append(
        _finding(
            "workflow-health",
            "warning" if unhealthy else "pass",
            "Workflow execution health",
            f"{unhealthy} failed or interrupted runs require review."
            if unhealthy
            else "No failed or interrupted workflow runs were found.",
            statuses=run_counts,
        )
    )

    summary = {
        severity: sum(1 for item in findings if item["severity"] == severity)
        for severity in ("critical", "warning", "pass")
    }
    return {"summary": summary, "findings": findings}


__all__ = ["router"]
