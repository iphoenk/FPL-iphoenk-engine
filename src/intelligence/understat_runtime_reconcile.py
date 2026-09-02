from __future__ import annotations

import re
import unicodedata
from typing import Any

from src.utils import DATA, atomic_json, read_json

RAW_CACHE = DATA / "stats" / "understat_epl_2026.json"
TACTICAL_OUT = DATA / "understat_tactical_v3.json"
HEALTH_OUT = DATA / "understat_tactical_health_v3.json"
LATEST_OUT = DATA / "latest.json"


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        return [row for row in value.values() if isinstance(row, dict)]
    return []


def _team_titles(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if value:
        return [part.strip() for part in str(value).split(",") if part.strip()]
    return []


def _is_completed_fixture(row: dict[str, Any]) -> bool:
    if row.get("isResult") is True or str(row.get("isResult") or "").lower() == "true":
        return True
    goals = row.get("goals")
    if isinstance(goals, dict) and goals.get("h") is not None and goals.get("a") is not None:
        return True
    return False


def latest_completed_match_covered(raw: dict[str, Any]) -> str | None:
    """Return only completed Understat match evidence, never future schedule."""
    represented = raw.get("latest_fixture_represented")
    if isinstance(represented, dict):
        stamp = represented.get("datetime") or represented.get("date")
        if stamp:
            return str(stamp)

    dates = _rows((raw.get("embedded") or {}).get("datesData"))
    completed = [row for row in dates if _is_completed_fixture(row)]
    stamps = [str(row.get("datetime") or row.get("date") or "") for row in completed]
    stamps = [stamp for stamp in stamps if stamp]
    return max(stamps) if stamps else None


def _strong_current_names(identity: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    primary = _norm(identity.get("name"))
    web = _norm(identity.get("web_name"))
    if primary:
        names.add(primary)
    if web:
        names.add(web)
    for value in identity.get("name_variants") or []:
        normalized = _norm(value)
        if normalized and len(normalized.split()) >= 2:
            names.add(normalized)
    return names


def classify_unlinked_source_players(raw: dict[str, Any], tactical: dict[str, Any]) -> list[dict[str, Any]]:
    """Classify unused source rows without fabricating a current-player link.

    A source row is review-worthy only when its strong identity exactly matches a
    player in the current Official universe but the governed mapper did not link
    it. Rows with no strong current identity are retained as historical/noncurrent
    source residue and do not count as a current-universe mapping defect.
    """
    player_evidence = tactical.get("player_evidence") or {}
    if not isinstance(player_evidence, dict):
        player_evidence = {}

    linked_source_ids = {
        str(row.get("understat_player_id"))
        for row in player_evidence.values()
        if isinstance(row, dict)
        and (row.get("mapping") or {}).get("state") == "RESOLVED"
        and row.get("understat_player_id") is not None
    }

    current_by_name: dict[str, set[int]] = {}
    for row in player_evidence.values():
        if not isinstance(row, dict):
            continue
        identity = row.get("canonical_identity") or {}
        try:
            element = int(identity.get("element") or row.get("element") or 0)
        except (TypeError, ValueError):
            continue
        if element <= 0:
            continue
        for name in _strong_current_names(identity):
            current_by_name.setdefault(name, set()).add(element)

    source_rows = _rows((raw.get("embedded") or {}).get("playersData"))
    out: list[dict[str, Any]] = []
    for source in source_rows:
        source_id = source.get("id")
        if source_id is None or str(source_id) in linked_source_ids:
            continue
        source_name = str(source.get("player_name") or source.get("name") or "")
        normalized = _norm(source_name)
        candidates = sorted(current_by_name.get(normalized) or set())
        if len(candidates) == 1:
            classification = "CURRENT_OFFICIAL_IDENTITY_UNLINKED"
            review_required = True
        elif len(candidates) > 1:
            classification = "AMBIGUOUS_CURRENT_OFFICIAL_IDENTITY"
            review_required = True
        else:
            classification = "NOT_IN_CURRENT_OFFICIAL_UNIVERSE"
            review_required = False
        out.append({
            "understat_player_id": str(source_id),
            "source_name": source_name,
            "source_teams": _team_titles(source.get("team_title") or source.get("team")),
            "classification": classification,
            "review_required": review_required,
            "current_official_candidates": candidates,
        })
    return out


def reconcile(out: dict[str, Any]) -> dict[str, Any]:
    """Reconcile V3 Understat publication truth inside the tactical owner."""
    tactical = out.get("tactical") or {}
    health = out.get("health") or {}
    raw = read_json(RAW_CACHE, {}) or {}

    latest_completed = latest_completed_match_covered(raw)
    tactical_source = tactical.setdefault("source", {})
    health_source = health.setdefault("source", {})
    tactical_source["latest_match_covered"] = latest_completed
    health_source["latest_match_covered"] = latest_completed
    health_source["latest_match_is_completed_evidence"] = latest_completed is not None

    classifications = classify_unlinked_source_players(raw, tactical)
    review_required = [row for row in classifications if row.get("review_required")]
    noncurrent = [row for row in classifications if row.get("classification") == "NOT_IN_CURRENT_OFFICIAL_UNIVERSE"]

    coverage = health.setdefault("coverage", {})
    coverage["source_player_unmapped_classifications"] = classifications
    coverage["source_player_mapping_review_required_count"] = len(review_required)
    coverage["source_player_historical_or_noncurrent_count"] = len(noncurrent)
    coverage["source_mapping_review_required"] = bool(review_required)

    official_count = int(coverage.get("official_universe_count") or 0)
    canonical_merge = health.get("canonical_merge") or {}
    merged_players = int(canonical_merge.get("player_profiles_enriched") or 0)
    identity_complete = bool(coverage.get("canonical_identity_mapping_complete"))
    merge_complete = official_count > 0 and merged_players == official_count
    coverage["current_universe_canonical_merge_complete"] = merge_complete
    coverage["current_universe_canonical_merge_coverage"] = (
        round(merged_players / official_count, 4) if official_count > 0 else 0.0
    )
    parity_ready = identity_complete and merge_complete and not review_required
    coverage["full_current_universe_parity_ready"] = parity_ready
    health["production_parity_status"] = "GREEN" if parity_ready else "REVIEW_REQUIRED"

    health.setdefault("governance", {}).update({
        "latest_match_covered_uses_completed_evidence_only": True,
        "unlinked_source_rows_are_classified_not_force_mapped": True,
        "historical_source_residue_does_not_reduce_current_official_identity_coverage": True,
        "current_identity_unlinked_source_rows_require_review": True,
    })

    out["tactical"] = tactical
    out["health"] = health
    atomic_json(TACTICAL_OUT, tactical)
    atomic_json(HEALTH_OUT, health)

    latest = read_json(LATEST_OUT, {}) or {}
    if latest:
        summary = latest.setdefault("understat_tactical_summary", {})
        summary["latest_match_covered"] = latest_completed
        summary["source_player_mapping_review_required_count"] = len(review_required)
        summary["current_universe_canonical_merge_complete"] = merge_complete
        summary["production_parity_status"] = health["production_parity_status"]
        atomic_json(LATEST_OUT, latest)
    return out
