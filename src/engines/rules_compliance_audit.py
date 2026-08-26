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
    # Deliberately conservative normalisation. Remote checks are opt-in because
    # editorial page changes can be unrelated to FPL rules.
    text = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
    state = {
        "ruleset_id": RULESET_ID,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "sources": current,
    }
    atomic_json(SOURCE_STATE, state)
    if changes:
        status = "REVIEW_REQUIRED"
    elif failures:
        status = "PARTIAL"
    else:
        status = "BASELINED" if not prior_sources else "NO_CHANGE"
    return {"status": status, "changed_sources": changes, "failed_sources": failures, "auto_mutation": False}


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
    drift = remote_drift_check() if check_remote else {
        "status": "NOT_RUN",
        "policy": "opt-in remote check; rules are never auto-mutated",
        "auto_mutation": False,
    }

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
    }, ensure_ascii=False))
    if overall == "FAIL":
        raise SystemExit(2)
    return out


def run() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-remote", action="store_true", default=os.getenv("FPL_RULES_REMOTE_CHECK", "").lower() in {"1", "true", "yes"})
    args = ap.parse_args()
    audit(check_remote=args.check_remote)


if __name__ == "__main__":
    run()
