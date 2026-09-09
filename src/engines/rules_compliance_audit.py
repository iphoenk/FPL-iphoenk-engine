from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from src.rules import (
    ACTIVE_RULESET,
    FINANCE_RULES,
    LINEUP_RULES,
    RULESET_ID,
    RULESET_SEASON,
    RULES_MANIFEST,
    SQUAD_RULES,
    active_ruleset_fingerprint,
)
from src.utils import DATA, ROOT, atomic_json, read_json

OUT = DATA / "rules_compliance.json"
SOURCE_STATE = DATA / "rules_source_state.json"
EXPECTED_SECTIONS = (
    "squad",
    "lineup",
    "scoring",
    "defensive_contributions",
    "chips",
    "finance",
    "bonus_bps",
)
REMOTE_DRIFT_STALE_AFTER_HOURS = 36.0
REMOTE_REFRESH_DUE_STATES = frozenset({"NOT_RUN", "STALE"})


def _status(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def _section_health() -> dict[str, dict[str, Any]]:
    provenance = ACTIVE_RULESET.get("rule_provenance") or {}
    sources = ACTIVE_RULESET.get("sources") or {}
    out: dict[str, dict[str, Any]] = {}
    for name in EXPECTED_SECTIONS:
        section = ACTIVE_RULESET.get(name)
        prov = provenance.get(name) or {}
        source_key = prov.get("source")
        source_url = sources.get(source_key) if source_key else None
        ok = isinstance(section, dict) and bool(section) and prov.get("verification") == "VERIFIED" and bool(source_url)
        out[name] = {
            "status": _status(ok),
            "verification": prov.get("verification"),
            "source_key": source_key,
            "source_url": source_url,
        }
    return out


def _semantic_checks() -> dict[str, dict[str, Any]]:
    pos = SQUAD_RULES.get("position_counts") or {}
    squad_size = int(SQUAD_RULES.get("squad_size") or 0)
    budget = int(SQUAD_RULES.get("budget_tenths") or 0)
    max_club = int(SQUAD_RULES.get("max_players_per_club") or 0)
    legal_forms = set(LINEUP_RULES.get("legal_formations") or [])
    xi_size = int(LINEUP_RULES.get("starting_xi_size") or 0)
    bench = LINEUP_RULES.get("bench") or {}
    chips = ACTIVE_RULESET.get("chips") or {}
    halves = chips.get("halves") or {}
    dc = ACTIVE_RULESET.get("defensive_contributions") or {}
    scoring = ACTIVE_RULESET.get("scoring") or {}
    sell = FINANCE_RULES.get("sell_value") or {}

    gw_coverage: list[int] = []
    for span in halves.values():
        if isinstance(span, list) and len(span) == 2:
            gw_coverage.extend(range(int(span[0]), int(span[1]) + 1))

    checks = {
        "squad_shape": {
            "ok": squad_size == 15 and sum(int(v) for v in pos.values()) == squad_size and pos == {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3},
            "detail": {"squad_size": squad_size, "position_counts": pos},
        },
        "budget_and_club_limit": {
            "ok": budget > 0 and max_club > 0,
            "detail": {"budget_tenths": budget, "max_players_per_club": max_club},
        },
        "lineup_contract": {
            "ok": xi_size == 11 and int(bench.get("goalkeepers") or 0) == 1 and int(bench.get("outfield") or 0) == 3 and len(legal_forms) >= 1,
            "detail": {"starting_xi_size": xi_size, "legal_formations": sorted(legal_forms), "bench": bench},
        },
        "chip_windows": {
            "ok": sorted(gw_coverage) == list(range(1, 39)) and len(gw_coverage) == len(set(gw_coverage)) and bool(chips.get("one_chip_per_gameweek")),
            "detail": {"halves": halves, "one_chip_per_gameweek": chips.get("one_chip_per_gameweek")},
        },
        "scoring_contract": {
            "ok": (scoring.get("goals") or {}).get("GK") == 10 and scoring.get("assists") == 3 and (scoring.get("bonus_awards") or []) == [3, 2, 1],
            "detail": {"goal_points": scoring.get("goals"), "assists": scoring.get("assists"), "bonus_awards": scoring.get("bonus_awards")},
        },
        "defcon_contract": {
            "ok": int(dc.get("points_cap_per_match") or -1) == 2 and (dc.get("by_position") or {}).get("GK", {}).get("eligible") is False,
            "detail": {"points_cap_per_match": dc.get("points_cap_per_match"), "positions": sorted((dc.get("by_position") or {}).keys())},
        },
        "sell_value_method": {
            "ok": sell.get("method") == "official_half_profit_floor",
            "detail": {"method": sell.get("method"), "rounding": sell.get("profit_share_rounding")},
        },
    }
    return {name: {"status": _status(bool(row["ok"])), **row["detail"]} for name, row in checks.items()}


def _source_text_fingerprint(html: str) -> str:
    # Deliberately conservative normalisation. Editorial/page-shell changes may
    # trigger review, but can never auto-mutate the governed rules registry.
    text = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _age_hours(iso_value: str | None) -> float | None:
    if not iso_value:
        return None
    try:
        parsed = datetime.fromisoformat(str(iso_value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 3600.0)
    except Exception:
        return None


def _changed_source_evidence(sources: dict[str, Any], changed_sources: list[str]) -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}
    for key in changed_sources:
        row = sources.get(key) or {}
        evidence[key] = {
            "url": row.get("url"),
            "http_status": row.get("http_status"),
            "previous_fingerprint_sha256": row.get("previous_fingerprint_sha256"),
            "current_fingerprint_sha256": row.get("fingerprint_sha256"),
        }
    return evidence


def _cached_remote_drift_state() -> dict[str, Any]:
    prior = read_json(SOURCE_STATE, {})
    prior_sources = prior.get("sources") or {}
    if not prior_sources:
        return {
            "status": "NOT_RUN",
            "policy": "governed remote baseline has not been persisted yet; rules are never auto-mutated",
            "cached": False,
            "auto_mutation": False,
            "changed_sources": [],
            "failed_sources": [],
            "changed_source_evidence": {},
        }

    changes = list(prior.get("changed_sources") or [key for key, row in prior_sources.items() if (row or {}).get("changed")])
    failures = list(prior.get("failed_sources") or [key for key, row in prior_sources.items() if (row or {}).get("error")])
    status = str(prior.get("status") or ("REVIEW_REQUIRED" if changes else "PARTIAL" if failures else "NO_CHANGE"))
    checked_at = prior.get("checked_at")
    age_hours = _age_hours(checked_at)
    stale = age_hours is None or age_hours > REMOTE_DRIFT_STALE_AFTER_HOURS
    if stale and status not in {"REVIEW_REQUIRED"}:
        status = "STALE"

    return {
        "status": status,
        "checked_at": checked_at,
        "age_hours": round(age_hours, 3) if age_hours is not None else None,
        "stale_after_hours": REMOTE_DRIFT_STALE_AFTER_HOURS,
        "cached": True,
        "changed_sources": changes,
        "failed_sources": failures,
        "changed_source_evidence": _changed_source_evidence(prior_sources, changes),
        "auto_mutation": False,
    }


def remote_drift_check() -> dict[str, Any]:
    prior = read_json(SOURCE_STATE, {})
    prior_sources = prior.get("sources") or {}
    current: dict[str, Any] = {}
    changes: list[str] = []
    failures: list[str] = []
    headers = {"User-Agent": "FPL-iphoenk-rules-auditor/1.0"}
    for key, url in (ACTIVE_RULESET.get("sources") or {}).items():
        try:
            r = requests.get(url, timeout=12, headers=headers)
            r.raise_for_status()
            fp = _source_text_fingerprint(r.text)
            old = (prior_sources.get(key) or {}).get("fingerprint_sha256")
            changed = bool(old and old != fp)
            if changed:
                changes.append(key)
            current[key] = {
                "url": url,
                "http_status": r.status_code,
                "fingerprint_sha256": fp,
                "previous_fingerprint_sha256": old,
                "changed": changed,
            }
        except Exception as exc:
            failures.append(key)
            current[key] = {"url": url, "error": str(exc), "changed": False}
    if changes:
        status = "REVIEW_REQUIRED"
    elif failures:
        status = "PARTIAL"
    else:
        status = "BASELINED" if not prior_sources else "NO_CHANGE"
    state = {
        "ruleset_id": RULESET_ID,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "changed_sources": changes,
        "failed_sources": failures,
        "sources": current,
    }
    atomic_json(SOURCE_STATE, state)
    return {
        "status": status,
        "checked_at": state["checked_at"],
        "cached": False,
        "changed_sources": changes,
        "failed_sources": failures,
        "changed_source_evidence": _changed_source_evidence(current, changes),
        "auto_mutation": False,
    }


def audit(check_remote: bool = False) -> dict[str, Any]:
    manifest_path = ROOT / "config" / "rules" / "registry.json"
    schema_path = ROOT / str(RULES_MANIFEST.get("schema_file") or "config/rules/schema.json")
    rules_path = ROOT / str(RULES_MANIFEST.get("rules_file") or "")

    integrity = {
        "manifest_exists": manifest_path.exists(),
        "schema_exists": schema_path.exists(),
        "rules_file_exists": rules_path.exists(),
        "active_ruleset_matches": RULES_MANIFEST.get("active_ruleset") == RULESET_ID,
        "season_matches": RULES_MANIFEST.get("season") == RULESET_SEASON,
        "authority_matches": RULES_MANIFEST.get("authority") == ACTIVE_RULESET.get("authority") == "Official FPL",
        "auto_mutate_rules": bool((RULES_MANIFEST.get("drift_policy") or {}).get("auto_mutate_rules")),
    }
    integrity_ok = all(v is True for k, v in integrity.items() if k != "auto_mutate_rules") and integrity["auto_mutate_rules"] is False

    sections = _section_health()
    semantic = _semantic_checks()
    section_ok = all(x.get("status") == "PASS" for x in sections.values())
    semantic_ok = all(x.get("status") == "PASS" for x in semantic.values())
    drift = remote_drift_check() if check_remote else _cached_remote_drift_state()

    if not integrity_ok or not section_ok or not semantic_ok:
        overall = "FAIL"
    elif drift.get("status") == "REVIEW_REQUIRED":
        overall = "REVIEW_REQUIRED"
    else:
        overall = "PASS"

    out = {
        "schema_version": 1,
        "ruleset_id": RULESET_ID,
        "season": RULESET_SEASON,
        "authority": ACTIVE_RULESET.get("authority"),
        "verified_at": ACTIVE_RULESET.get("verified_at"),
        "ruleset_fingerprint_sha256": active_ruleset_fingerprint(),
        "overall": overall,
        "registry_integrity": {"status": _status(integrity_ok), **integrity},
        "sections": sections,
        "semantic_checks": semantic,
        "drift": drift,
        "change_policy": RULES_MANIFEST.get("change_policy"),
        "governance": {
            "single_source_of_truth": True,
            "consumers_must_load_registry": True,
            "remote_change_never_auto_mutates_rules": True,
            "registry_integrity_failure_blocks_go": True,
            "remote_drift_refresh_is_freshness_driven": True,
            "persisted_remote_drift_state_is_reused_between_checks": True,
        },
    }
    atomic_json(OUT, out)
    print(json.dumps({
        "rules": overall,
        "ruleset_id": RULESET_ID,
        "registry_integrity": integrity_ok,
        "sections_pass": sum(1 for x in sections.values() if x.get("status") == "PASS"),
        "semantic_pass": sum(1 for x in semantic.values() if x.get("status") == "PASS"),
        "drift": drift.get("status"),
        "changed_sources": drift.get("changed_sources") or [],
        "failed_sources": drift.get("failed_sources") or [],
    }, ensure_ascii=False))
    if overall == "FAIL":
        raise SystemExit(2)
    return out


def refresh_if_due() -> dict[str, Any]:
    """Canonical rules capability freshness gate.

    Thresholds, fingerprints and mutation policy remain owned by this auditor.
    A remote request is made only when the persisted evidence is stale/missing.
    REVIEW_REQUIRED is never auto-cleared and is surfaced with exact source and
    fingerprint evidence so a human review can be specific and reproducible.
    """
    cached = audit(check_remote=False)
    cached_drift = cached.get("drift") or {}
    before = str(cached_drift.get("status") or "NOT_RUN")

    if before == "REVIEW_REQUIRED":
        return {
            "status": "MANUAL_REVIEW_REQUIRED",
            "remote_check_executed": False,
            "drift_before": before,
            "drift_after": before,
            "rules_overall": cached.get("overall"),
            "changed_sources": cached_drift.get("changed_sources") or [],
            "failed_sources": cached_drift.get("failed_sources") or [],
            "changed_source_evidence": cached_drift.get("changed_source_evidence") or {},
        }

    if before not in REMOTE_REFRESH_DUE_STATES:
        return {
            "status": "FRESH",
            "remote_check_executed": False,
            "drift_before": before,
            "drift_after": before,
            "rules_overall": cached.get("overall"),
            "changed_sources": cached_drift.get("changed_sources") or [],
            "failed_sources": cached_drift.get("failed_sources") or [],
            "changed_source_evidence": cached_drift.get("changed_source_evidence") or {},
        }

    refreshed = audit(check_remote=True)
    refreshed_drift = refreshed.get("drift") or {}
    after = str(refreshed_drift.get("status") or "UNKNOWN")
    status = "MANUAL_REVIEW_REQUIRED" if after == "REVIEW_REQUIRED" else "REFRESHED"
    return {
        "status": status,
        "remote_check_executed": True,
        "drift_before": before,
        "drift_after": after,
        "rules_overall": refreshed.get("overall"),
        "changed_sources": refreshed_drift.get("changed_sources") or [],
        "failed_sources": refreshed_drift.get("failed_sources") or [],
        "changed_source_evidence": refreshed_drift.get("changed_source_evidence") or {},
    }


def run() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-remote", action="store_true", default=os.getenv("FPL_RULES_REMOTE_CHECK", "").lower() in {"1", "true", "yes"})
    ap.add_argument("--cached-only", action="store_true", help="Read persisted rules drift state without a freshness-triggered remote check")
    args = ap.parse_args()
    if args.check_remote and args.cached_only:
        raise SystemExit("--check-remote and --cached-only are mutually exclusive")

    if args.check_remote:
        result = audit(check_remote=True)
        if result.get("overall") == "REVIEW_REQUIRED":
            raise SystemExit(3)
        return
    if args.cached_only:
        result = audit(check_remote=False)
        if result.get("overall") == "REVIEW_REQUIRED":
            raise SystemExit(3)
        return

    result = refresh_if_due()
    print("V3_RULES_REFRESH=" + json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    if result.get("status") == "MANUAL_REVIEW_REQUIRED":
        raise SystemExit(3)


if __name__ == "__main__":
    run()
