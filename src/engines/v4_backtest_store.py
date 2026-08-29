from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from src.utils import DATA, atomic_json, parse_dt, read_json, utcnow

SNAPDIR = DATA / "validation" / "deadline"
ARCHIVE_RECDIR = DATA / "validation" / "archive" / "reconciled"
# Framework health intentionally reads this directory. It is an eligibility view,
# rebuilt by the validation lifecycle from immutable archived reconciliations.
RECDIR = DATA / "validation" / "reconciled"
COMPACT_PROJECTION = "reconciliation_minimal_v2"
LEGACY_COMPACT_PROJECTION = "reconciliation_minimal_v1"


def deadline_snapshot_path(gw: int) -> Path:
    return SNAPDIR / f"gw{int(gw):02d}.json"


def reconciled_path(gw: int) -> Path:
    return ARCHIVE_RECDIR / f"gw{int(gw):02d}.json"


def eligible_reconciled_path(gw: int) -> Path:
    return RECDIR / f"gw{int(gw):02d}.json"


def _digest(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _aware(value: datetime | None) -> bool:
    return value is not None and value.tzinfo is not None


def deadline_player_projection(players: list[dict], gw: int) -> tuple[list[dict], int]:
    """Keep only point-in-time fields consumed by post-GW reconciliation.

    DNP probability and the explicit tactical delta are retained so calibration
    and tactical-ablation metrics remain lossless without storing the verbose
    full prediction artifact.
    """
    projected: list[dict] = []
    target_fixture_rows = 0
    for player in players:
        if player.get("element") is None:
            raise RuntimeError("prediction player missing element id")
        fixture = next((row for row in (player.get("fixtures") or []) if int(row.get("event") or -1) == int(gw)), None)
        fixtures: list[dict] = []
        if fixture is not None:
            xmins = fixture.get("xmins") or {}
            components = fixture.get("components") or {}
            fixtures.append({
                "event": int(gw),
                "xpts": fixture.get("xpts"),
                "lower80": fixture.get("lower80"),
                "upper80": fixture.get("upper80"),
                "xmins": {
                    "expected_minutes": xmins.get("expected_minutes"),
                    "start_probability": xmins.get("start_probability"),
                    "dnp_probability": xmins.get("dnp_probability"),
                    "p60": xmins.get("p60"),
                },
                "components": {
                    "tactical_adjustment": components.get("tactical_adjustment", 0.0),
                },
            })
            target_fixture_rows += 1
        projected.append({"element": int(player["element"]), "name": player.get("name"), "position": player.get("position"), "fixtures": fixtures})
    return projected, target_fixture_rows


def snapshot_integrity(snapshot: dict, expected_gw: int | None = None) -> tuple[bool, str | None]:
    if not snapshot or snapshot.get("kind") != "deadline_prediction_snapshot":
        return False, "wrong_snapshot_kind"
    if snapshot.get("point_in_time") is not True or snapshot.get("immutable") is not True:
        return False, "snapshot_not_immutable_point_in_time"
    if expected_gw is not None and int(snapshot.get("gw") or -1) != int(expected_gw):
        return False, "snapshot_gw_mismatch"
    if not snapshot.get("model_version") or not list(snapshot.get("players") or []):
        return False, "snapshot_missing_model_or_players"
    deadline = parse_dt(snapshot.get("deadline_time"))
    prediction_generated = parse_dt(snapshot.get("prediction_generated_at") or snapshot.get("generated_at"))
    captured = parse_dt(snapshot.get("captured_at"))
    if not (_aware(deadline) and _aware(prediction_generated) and _aware(captured)):
        return False, "snapshot_timestamps_invalid"
    if prediction_generated > deadline or captured > deadline:
        return False, "snapshot_created_after_deadline"
    projection = snapshot.get("projection")
    if projection is not None:
        if projection not in {COMPACT_PROJECTION, LEGACY_COMPACT_PROJECTION}:
            return False, "unknown_snapshot_projection"
        gw = int(snapshot.get("gw") or -1)
        fixture_rows = 0
        for player in snapshot.get("players") or []:
            fixtures = list(player.get("fixtures") or [])
            if len(fixtures) > 1:
                return False, "compact_snapshot_has_multiple_fixtures"
            if fixtures:
                fixture = fixtures[0]
                if int(fixture.get("event") or -1) != gw:
                    return False, "compact_snapshot_fixture_gw_mismatch"
                xmins = fixture.get("xmins") or {}
                required = ("expected_minutes", "start_probability", "p60")
                if projection == COMPACT_PROJECTION:
                    required = (*required, "dnp_probability")
                if fixture.get("xpts") is None or any(xmins.get(field) is None for field in required):
                    return False, "compact_snapshot_missing_reconciliation_fields"
                if projection == COMPACT_PROJECTION and "tactical_adjustment" not in (fixture.get("components") or {}):
                    return False, "compact_snapshot_missing_tactical_ablation_field"
                fixture_rows += 1
        if int(snapshot.get("source_players") or -1) != len(snapshot.get("players") or []):
            return False, "compact_snapshot_source_player_count_mismatch"
        if int(snapshot.get("target_fixture_rows") or -1) != fixture_rows:
            return False, "compact_snapshot_fixture_count_mismatch"
    return True, None


def persist_deadline_snapshot(gw: int, deadline_time: str | None, predictions: dict, generated_at: str | None = None, now: datetime | None = None) -> dict:
    path = deadline_snapshot_path(gw)
    existing = read_json(path, None)
    if existing:
        ok, reason = snapshot_integrity(existing, int(gw))
        if not ok:
            raise RuntimeError(f"existing deadline snapshot failed integrity: {reason}")
        existing_deadline = parse_dt(existing.get("deadline_time"))
        requested_deadline = parse_dt(deadline_time)
        if not requested_deadline or existing_deadline != requested_deadline:
            raise RuntimeError("existing deadline snapshot deadline mismatch")
        return existing
    deadline = parse_dt(deadline_time)
    current = now or utcnow()
    if not (_aware(deadline) and _aware(current)):
        raise RuntimeError("deadline snapshot requires timezone-aware timestamps")
    if current >= deadline:
        raise RuntimeError("retroactive deadline snapshot rejected")
    prediction_generated_at = generated_at or predictions.get("generated_at")
    prediction_generated = parse_dt(prediction_generated_at)
    if not _aware(prediction_generated):
        raise RuntimeError("prediction generated_at missing or timezone-naive")
    if prediction_generated > deadline:
        raise RuntimeError("prediction artifact was generated after deadline")
    source_players = list(predictions.get("players") or [])
    model_version = predictions.get("model_version")
    if not source_players or not model_version:
        raise RuntimeError("prediction snapshot missing model_version or players")
    players, target_fixture_rows = deadline_player_projection(source_players, int(gw))
    if target_fixture_rows <= 0:
        raise RuntimeError("prediction snapshot has no target-GW fixtures")
    payload = {
        "schema_version": 4962,
        "kind": "deadline_prediction_snapshot",
        "gw": int(gw),
        "deadline_time": deadline_time,
        "generated_at": prediction_generated_at,
        "prediction_generated_at": prediction_generated_at,
        "captured_at": current.isoformat(),
        "model_version": model_version,
        "point_in_time": True,
        "immutable": True,
        "prediction_sha256": _digest(predictions),
        "projection": COMPACT_PROJECTION,
        "source_players": len(source_players),
        "target_fixture_rows": target_fixture_rows,
        "players": players,
    }
    ok, reason = snapshot_integrity(payload, int(gw))
    if not ok:
        raise RuntimeError(f"deadline snapshot failed integrity before write: {reason}")
    atomic_json(path, payload)
    return payload


def reconciled_integrity(sample: dict, model_version: str | None = None) -> tuple[bool, str | None]:
    if not sample or sample.get("kind") != "post_gw_reconciliation":
        return False, "wrong_reconciliation_kind"
    if sample.get("immutable") is not True or sample.get("sample_eligible") is not True:
        return False, "reconciliation_not_immutable_or_eligible"
    if model_version and sample.get("model_version") != model_version:
        return False, "model_version_mismatch"
    metrics = ((sample.get("report") or {}).get("metrics") or {})
    if metrics.get("status") != "PASS" or int(metrics.get("n") or 0) <= 0:
        return False, "reconciliation_metrics_not_passed"
    if int(metrics.get("leakage_rejected") or 0) != 0:
        return False, "reconciliation_contains_leakage_rejections"
    gw = int(sample.get("gw") or -1)
    snapshot = read_json(deadline_snapshot_path(gw), None)
    ok, reason = snapshot_integrity(snapshot, gw)
    if not ok:
        return False, f"source_snapshot_invalid:{reason}"
    if _digest(snapshot) != sample.get("source_snapshot_sha256"):
        return False, "source_snapshot_digest_mismatch"
    if snapshot.get("model_version") != sample.get("model_version"):
        return False, "source_snapshot_model_mismatch"
    return True, None


def refresh_eligible_view(model_version: str | None) -> dict:
    RECDIR.mkdir(parents=True, exist_ok=True)
    for path in RECDIR.glob("gw*.json"):
        path.unlink()
    eligible: list[int] = []
    rejected: list[dict] = []
    if ARCHIVE_RECDIR.exists():
        for path in sorted(ARCHIVE_RECDIR.glob("gw*.json")):
            sample = read_json(path, {})
            ok, reason = reconciled_integrity(sample, model_version=model_version)
            if not ok:
                rejected.append({"file": path.name, "reason": reason})
                continue
            gw = int(sample.get("gw"))
            atomic_json(eligible_reconciled_path(gw), sample)
            eligible.append(gw)
    return {
        "model_version": model_version,
        "eligible_samples": len(eligible),
        "eligible_gws": eligible,
        "rejected_samples": rejected,
        "archive_is_append_only": True,
        "health_view_rebuilt": True,
    }
