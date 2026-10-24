from __future__ import annotations

"""Read-only HTTP boundary for the canonical V12 decision runtime.

This module deliberately contains no prediction or optimisation logic.  It
only authenticates the configured entry, invokes the already governed
``unified_fastpath`` and maps its result to the dashboard contract.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from src.runtime_v3.unified_fastpath import run as run_unified_fastpath
from src.settings import TEAM_ID
from src.utils import DATA, ROOT
from src.version import ENGINE_VERSION

CONTRACT = "FPL_V12_CANONICAL_DECISION_V1"
ALLOWED_HORIZONS = {1, 3, 5}
_ARTIFACT_NAMES = (
    "latest.json",
    "projections.json",
    "package_optimizer.json",
    "team.json",
    "chips.json",
    "framework_health.json",
    "decision_brief.json",
    "user_report.json",
)

app = FastAPI(title="FPL V12 Canonical Decision Service", version=ENGINE_VERSION)


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _artifact_fingerprints(data_dir: Path) -> dict[str, str]:
    return {
        name: digest
        for name in _ARTIFACT_NAMES
        if (digest := _sha256(data_dir / name)) is not None
    }


def _canonical_revision() -> str | None:
    return _sha256(ROOT / "control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt")


def _entry_id_from_team(team: Any) -> int | None:
    if not isinstance(team, dict):
        return None
    for key in ("entry_id", "team_id", "id"):
        value = team.get(key)
        if value not in (None, ""):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    return None


def _configured_entry_id() -> int:
    # The configured identity is the only identity this service may serve.
    return int(os.getenv("FPL_TEAM_ID") or TEAM_ID)


def _routes(package: dict[str, Any]) -> list[dict[str, Any]]:
    raw = package.get("package_frontier")
    if isinstance(raw, dict):
        raw = raw.get("routes") or raw.get("packages") or []
    return [dict(row) for row in (raw or []) if isinstance(row, dict)]


def _scenario_summary(package: dict[str, Any]) -> dict[str, Any]:
    """Expose real frontier rows without fabricating A/B/C recommendations."""
    routes = _routes(package)
    selected = package.get("selected_package") or {}
    return {
        "selected_package_id": package.get("selected_package_id"),
        "selected_package": selected,
        "frontier": routes,
        "A": next((row for row in routes if str(row.get("route_id")) == "HOLD"), None),
        "B": None,
        "C": None,
        "mapping_status": "RAW_FRONTIER_ONLY",
        "mapping_note": "A/B/C labels are not invented when the canonical frontier does not provide them.",
    }


def _payload(entry_id: int, horizon: int, result: dict[str, Any]) -> dict[str, Any]:
    lineup = result.get("lineup") or {}
    package = result.get("package") or {}
    authority = result.get("authority") or {}
    data_dir = Path(os.getenv("FPL_DATA_DIR") or DATA)
    fingerprints = _artifact_fingerprints(data_dir)
    binding = package.get("model_evidence_binding") or {}
    input_fingerprint = binding.get("input_fingerprint") or hashlib.sha256(
        json.dumps(fingerprints, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    canonical_revision = binding.get("canonical_v12_revision") or _canonical_revision()
    owned_15 = result.get("owned_15")
    required = (
        isinstance(owned_15, list)
        and len(owned_15) == 15
        and bool(lineup.get("formation"))
        and len(lineup.get("starting_xi") or []) == 11
        and bool(canonical_revision)
        and bool(input_fingerprint)
        and authority.get("governed_decision_recomputed") is True
        and authority.get("network_fetches") == 0
    )
    status = "ready" if required else "degraded"
    warnings = [] if required else ["CANONICAL_RUNTIME_OUTPUT_INCOMPLETE"]
    return {
        "contract": CONTRACT,
        "status": status,
        "entry_id": entry_id,
        "horizon": horizon,
        "planning_gw": result.get("planning_gw"),
        "owned_15": owned_15,
        "decision": {
            "starting_xi": lineup.get("starting_xi"),
            "bench": lineup.get("bench"),
            "formation": lineup.get("formation"),
            "captain": lineup.get("captain"),
            "vice_captain": lineup.get("vice_captain"),
            "scenarios": _scenario_summary(package),
            "risk": {
                "lineup_score": lineup.get("lineup_score"),
                "monte_carlo": package.get("monte_carlo"),
                "decision": package.get("decision"),
            },
            "lineup": lineup,
            "package": package,
        },
        "provenance": {
            "input_fingerprint": input_fingerprint,
            "canonical_v12_revision": canonical_revision,
            "engine_version": ENGINE_VERSION,
            "ruleset_id": lineup.get("ruleset_id") or package.get("ruleset_id"),
            "artifact_fingerprints": fingerprints,
            "serving_mode": result.get("serving_mode"),
            "freshness": result.get("freshness"),
            "authority": authority,
        },
        "warnings": warnings,
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "contract": CONTRACT, "engine_version": ENGINE_VERSION}


@app.get("/api/decision")
def decision(
    entry_id: int = Query(..., ge=1),
    horizon: int = Query(1),
) -> JSONResponse:
    if horizon not in ALLOWED_HORIZONS:
        raise HTTPException(status_code=400, detail="horizon must be one of 1, 3 or 5")
    configured = _configured_entry_id()
    if entry_id != configured:
        raise HTTPException(status_code=403, detail="entry_id is not authorised for this service")

    # The artifact identity must also agree when team.json is available.
    team_path = Path(os.getenv("FPL_DATA_DIR") or DATA) / "team.json"
    if team_path.is_file():
        try:
            team = json.loads(team_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=503, detail="canonical team artifact is unreadable") from exc
        artifact_entry = _entry_id_from_team(team)
        if artifact_entry is not None and artifact_entry != configured:
            raise HTTPException(status_code=503, detail="canonical team identity does not match configured entry")

    try:
        result = run_unified_fastpath()
        payload = _payload(entry_id, horizon, result)
    except Exception as exc:
        # Do not leak file paths, stack traces or internal model data over the
        # public decision boundary.  Refresh is an operational concern.
        return JSONResponse(
            status_code=503,
            content={
                "contract": CONTRACT,
                "status": "unavailable",
                "entry_id": entry_id,
                "horizon": horizon,
                "error": "canonical artifacts are not ready",
            },
        )
    if payload["status"] != "ready":
        return JSONResponse(status_code=503, content=payload)
    return JSONResponse(content=payload)

