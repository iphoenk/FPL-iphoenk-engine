from __future__ import annotations

import re
import unicodedata
from typing import Any

from src.intelligence.understat_tactical import _confidence, _policy, _understat_players
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


def _refresh_canonical_merge(tactical: dict[str, Any]) -> dict[str, int]:
    """Re-run the existing idempotent canonical merge after a source-link repair."""
    from src.engines.understat_tactical_context import _merge_canonical_tactical_artifacts

    return _merge_canonical_tactical_artifacts(tactical)


def repair_exact_identity_source_team_drift(raw: dict[str, Any], tactical: dict[str, Any]) -> list[dict[str, Any]]:
    """Repair only unique exact multi-token identities blocked by source-team drift.

    Official FPL remains the current team/position authority. Understat team context
    is retained as provenance, never copied over the Official team. No first-name,
    surname-only, fuzzy, or ambiguous cross-team match is permitted.
    """
    policy = _policy()
    identity_policy = policy.get("identity") or {}
    if identity_policy.get("cross_team_unique_exact_multi_token_fallback", True) is not True:
        return []

    player_evidence = tactical.get("player_evidence") or {}
    if not isinstance(player_evidence, dict):
        return []

    linked_source_ids = {
        str(row.get("understat_player_id"))
        for row in player_evidence.values()
        if isinstance(row, dict)
        and (row.get("mapping") or {}).get("state") == "RESOLVED"
        and row.get("understat_player_id") is not None
    }
    candidates = [
        row for row in _understat_players(raw)
        if row.get("understat_player_id") is not None
        and str(row.get("understat_player_id")) not in linked_source_ids
    ]

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
            if len(name.split()) >= 2:
                current_by_name.setdefault(name, set()).add(element)

    source_by_name: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        name = _norm(candidate.get("normalized_name") or candidate.get("name"))
        if name and len(name.split()) >= 2:
            source_by_name.setdefault(name, []).append(candidate)

    fallback_confidence = float(identity_policy.get("cross_team_exact_confidence") or 0.95)
    repaired: list[dict[str, Any]] = []
    consumed_source_ids: set[str] = set()

    for row in player_evidence.values():
        if not isinstance(row, dict) or (row.get("mapping") or {}).get("state") == "RESOLVED":
            continue
        identity = row.get("canonical_identity") or {}
        try:
            element = int(identity.get("element") or row.get("element") or 0)
        except (TypeError, ValueError):
            continue
        official_team = _norm(identity.get("team"))
        if element <= 0 or not official_team:
            continue

        matches: dict[str, dict[str, Any]] = {}
        for name in _strong_current_names(identity):
            if len(name.split()) < 2 or current_by_name.get(name) != {element}:
                continue
            source_matches = source_by_name.get(name) or []
            if len(source_matches) != 1:
                continue
            candidate = source_matches[0]
            source_id = str(candidate.get("understat_player_id"))
            if source_id in consumed_source_ids:
                continue
            source_teams = [_norm(team) for team in candidate.get("teams") or [] if _norm(team)]
            # Same-team unresolved evidence is a real mapper defect and remains reviewable.
            if official_team in source_teams:
                continue
            matches[source_id] = candidate

        if len(matches) != 1:
            continue

        source_id, candidate = next(iter(matches.items()))
        season = candidate.get("season_to_date") or {}
        matches_played = int(season.get("matches") or 0)
        sample_state, sample_confidence = _confidence(matches_played, policy)
        source_teams = list(candidate.get("teams") or [])
        row.update({
            "understat_player_id": candidate.get("understat_player_id"),
            "understat_name": candidate.get("name"),
            "mapping": {
                "state": "RESOLVED",
                "confidence": round(fallback_confidence, 4),
                "method": "CURRENT_OFFICIAL_IDENTITY_EXACT_SOURCE_TEAM_DRIFT",
                "source_team_mismatch": True,
                "source_teams": source_teams,
                "official_team_authority": identity.get("team"),
            },
            "season_to_date": {
                **season,
                "sample_state": sample_state,
                "confidence": round(sample_confidence * fallback_confidence, 4),
            },
            "rolling_windows": {
                "last_1": {"state": "INSUFFICIENT_EVIDENCE", "reason": "PLAYER_MATCH_SERIES_NOT_SUPPLIED_BY_GOVERNED_SNAPSHOT"},
                "last_3": {"state": "INSUFFICIENT_EVIDENCE", "reason": "PLAYER_MATCH_SERIES_NOT_SUPPLIED_BY_GOVERNED_SNAPSHOT"},
                "last_5": {"state": "INSUFFICIENT_EVIDENCE", "reason": "PLAYER_MATCH_SERIES_NOT_SUPPLIED_BY_GOVERNED_SNAPSHOT"},
            },
            "missingness": None,
        })
        consumed_source_ids.add(source_id)
        repaired.append({
            "element": element,
            "official_name": identity.get("name"),
            "official_team": identity.get("team"),
            "understat_player_id": source_id,
            "understat_name": candidate.get("name"),
            "source_teams": source_teams,
            "method": "CURRENT_OFFICIAL_IDENTITY_EXACT_SOURCE_TEAM_DRIFT",
        })

    if repaired:
        repaired_elements = {int(row["element"]) for row in repaired}
        tactical["unresolved_mappings"] = [
            row for row in (tactical.get("unresolved_mappings") or [])
            if int((row or {}).get("element") or 0) not in repaired_elements
        ]
    return repaired


def _refresh_mapping_health(raw: dict[str, Any], tactical: dict[str, Any], coverage: dict[str, Any]) -> None:
    player_evidence = tactical.get("player_evidence") or {}
    if not isinstance(player_evidence, dict):
        player_evidence = {}
    source_rows = _rows((raw.get("embedded") or {}).get("playersData"))
    source_ids = {str(row.get("id")) for row in source_rows if row.get("id") is not None}
    resolved_rows = [
        row for row in player_evidence.values()
        if isinstance(row, dict) and (row.get("mapping") or {}).get("state") == "RESOLVED"
    ]
    resolved_source_ids = {
        str(row.get("understat_player_id"))
        for row in resolved_rows
        if row.get("understat_player_id") is not None
    }
    official_count = int(coverage.get("official_universe_count") or len(player_evidence) or 0)
    source_count = len(source_ids)
    unresolved_count = sum(
        (row.get("mapping") or {}).get("state") != "RESOLVED"
        for row in player_evidence.values()
        if isinstance(row, dict)
    )
    method_counts: dict[str, int] = {}
    for row in resolved_rows:
        method = str((row.get("mapping") or {}).get("method") or "UNKNOWN")
        method_counts[method] = method_counts.get(method, 0) + 1

    coverage.update({
        "source_linked_mapping_count": len(resolved_rows),
        "source_linked_mapping_coverage": round(len(resolved_rows) / max(1, official_count), 4),
        "source_unlinked_official_count": unresolved_count,
        "source_player_count": source_count,
        "source_player_mapping_count": len(source_ids & resolved_source_ids),
        "source_player_mapping_coverage": round(len(source_ids & resolved_source_ids) / max(1, source_count), 4),
        "source_player_unmapped_count": max(0, source_count - len(source_ids & resolved_source_ids)),
        "unresolved_mapping_count": unresolved_count,
        "mapping_method_counts": dict(sorted(method_counts.items())),
    })


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

    drift_repairs = repair_exact_identity_source_team_drift(raw, tactical)
    coverage = health.setdefault("coverage", {})
    if drift_repairs:
        health["canonical_merge"] = _refresh_canonical_merge(tactical)
    _refresh_mapping_health(raw, tactical, coverage)

    classifications = classify_unlinked_source_players(raw, tactical)
    review_required = [row for row in classifications if row.get("review_required")]
    noncurrent = [row for row in classifications if row.get("classification") == "NOT_IN_CURRENT_OFFICIAL_UNIVERSE"]

    coverage["source_player_unmapped_classifications"] = classifications
    coverage["source_player_mapping_review_required_count"] = len(review_required)
    coverage["source_player_historical_or_noncurrent_count"] = len(noncurrent)
    coverage["source_mapping_review_required"] = bool(review_required)
    coverage["source_team_drift_repaired_count"] = len(drift_repairs)
    coverage["source_team_drift_repairs"] = drift_repairs

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
        "cross_team_source_drift_requires_unique_exact_multi_token_identity": True,
        "cross_team_source_drift_never_overrides_official_team_authority": True,
        "cross_team_fuzzy_identity_mapping_forbidden": True,
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
        summary["source_team_drift_repaired_count"] = len(drift_repairs)
        summary["current_universe_canonical_merge_complete"] = merge_complete
        summary["production_parity_status"] = health["production_parity_status"]
        atomic_json(LATEST_OUT, latest)
    return out
