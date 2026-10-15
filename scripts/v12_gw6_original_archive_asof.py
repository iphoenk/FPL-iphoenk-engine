#!/usr/bin/env python3
"""Verify an ORIGINAL pre-GW6 Official FPL archive, never retrofit timestamps.

Uses the exact old Git commit, its original artifact catalog, source event_live
bodies and normalized player_match rows. Only GW6 *training-input* as-of can
PASS; this is NOT proof of a predeadline model forecast or full GW1-GW6 gate.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

ORIGINAL_COMMIT = "55763bbe237c9a673e55325f79b6f81d1afc7d27"
ORIGINAL_RUN_ID = 35727337207
SOURCE_PATH = "data/v6/current/official_fpl.json"
NORMALIZED_PATH = "data/v6/normalized/sources/official_fpl.json"
CATALOG_PATH = "data/v6/evidence/artifact_catalog.json"
VALID_IDENTITIES = {"EXACT", "VERIFIED", "VERIFIED_MANUAL"}
EXPECTED_GW_ROWS = {1: 593, 2: 618, 3: 654, 4: 659, 5: 667}


class HistoricalAsOfError(ValueError):
    pass


def _date(value: object) -> datetime:
    if not isinstance(value, str):
        raise HistoricalAsOfError("SOURCE_TIMESTAMP_MISSING")
    try:
        out = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HistoricalAsOfError("SOURCE_TIMESTAMP_INVALID") from exc
    if out.tzinfo is None:
        raise HistoricalAsOfError("SOURCE_TIMESTAMP_NAIVE")
    return out.astimezone(timezone.utc)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_original_gw6_archive(
    *, source_bytes: bytes, normalized_bytes: bytes, catalog_bytes: bytes,
    immutable_commit_at: str, immutable_commit_sha: str,
) -> dict[str, object]:
    if immutable_commit_sha != ORIGINAL_COMMIT:
        raise HistoricalAsOfError("ORIGINAL_COMMIT_NOT_ALLOWLISTED")
    source, normalized, catalog = (
        json.loads(blob) for blob in (source_bytes, normalized_bytes, catalog_bytes)
    )
    if source.get("source_id") != "official_fpl" or normalized.get("source_id") != "official_fpl":
        raise HistoricalAsOfError("ORIGINAL_SOURCE_ID_MISMATCH")
    artifacts = {row.get("path"): row for row in catalog.get("artifacts") or []
                 if isinstance(row, dict)}
    for path, blob in ((SOURCE_PATH, source_bytes), (NORMALIZED_PATH, normalized_bytes)):
        artifact = artifacts.get(path) or {}
        if (artifact.get("source_id") != "official_fpl"
                or artifact.get("origin_run_id") != str(ORIGINAL_RUN_ID)
                and artifact.get("origin_run_id") != ORIGINAL_RUN_ID
                or artifact.get("sha256") != _digest(blob)
                or artifact.get("status") != "PROVEN"):
            raise HistoricalAsOfError("IMMUTABLE_CATALOG_SHA_OR_SOURCE_MISMATCH")

    if normalized.get("normalization_status") != "NORMALIZED":
        raise HistoricalAsOfError("ARCHIVED_NORMALIZATION_UNAVAILABLE")
    committed = _date(immutable_commit_at)
    captured = _date(source.get("checked_at"))
    effective = _date(normalized.get("effective_at"))
    generated = _date(normalized.get("generated_at"))
    bootstrap = ((source.get("data") or {}).get("bootstrap") or {}).get("json") or {}
    events = {e.get("id"): e for e in bootstrap.get("events") or [] if isinstance(e, dict)}
    deadline = _date((events.get(6) or {}).get("deadline_time"))
    if not (captured <= committed < deadline and effective <= committed
            and generated <= committed):
        raise HistoricalAsOfError("ARCHIVE_NOT_ORIGINALLY_PREDEADLINE")

    games = [f for f in (source.get("data") or {}).get("fixtures", {}).get("json") or []
             if isinstance(f, dict) and f.get("event") in range(1, 6)]
    fixtures = {f.get("id"): f for f in games if isinstance(f.get("id"), int)}
    per_gw_fixtures = Counter(f.get("event") for f in games)
    if (len(games) != 50 or len(fixtures) != 50
            or any(per_gw_fixtures.get(gw) != 10 for gw in range(1, 6))
            or any(f.get("finished") is not True for f in games)):
        raise HistoricalAsOfError("ORIGINAL_FINISHED_FIXTURE_COVERAGE_INCOMPLETE")

    snapshots = normalized.get("source_snapshot_ids") or []
    lives = {}
    for gw in range(1, 6):
        event = events.get(gw) or {}
        if event.get("finished") is not True or event.get("data_checked") is not True:
            raise HistoricalAsOfError("ORIGINAL_GW_NOT_DATA_CHECKED_FINAL")
        snap = (source.get("data") or {}).get(f"event_live_gw{gw}") or {}
        if (snap.get("status") != "AVAILABLE"
                or not isinstance(snap.get("json"), dict)
                or not isinstance(snap["json"].get("elements"), dict)
                or not isinstance(snap.get("sha256"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", snap["sha256"])
                or snap["sha256"] not in snapshots
                or _date(snap.get("checked_at")) > committed):
            raise HistoricalAsOfError("ORIGINAL_GW_EVENT_LIVE_PROVENANCE_MISSING")
        lives[gw] = snap["json"]["elements"]
        if sum(x.get("stats", {}).get("starts") == 1
               for x in lives[gw].values() if isinstance(x, dict)) != 220:
            raise HistoricalAsOfError("ORIGINAL_GW_STARTER_OBSERVATIONS_INCOMPLETE")

    rows = (normalized.get("record_groups") or {}).get("player_matches") or []
    counts = Counter()
    keys: set[tuple[int, int, int]] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise HistoricalAsOfError("NON_MAPPING_ARCHIVED_PLAYER_ROW")
        gw, pid, fixture = (row.get("gw"), row.get("official_element_id"),
                            row.get("official_fixture_id"))
        if (gw not in range(1, 6) or not isinstance(pid, int)
                or not isinstance(fixture, int)
                or row.get("identity_status") not in VALID_IDENTITIES
                or row.get("fixture_identity_status") not in VALID_IDENTITIES
                or row.get("opponent_identity_status") not in VALID_IDENTITIES):
            raise HistoricalAsOfError("ORIGINAL_PLAYER_FIXTURE_IDENTITY_UNVERIFIED")
        key = (gw, pid, fixture)
        if key in keys:
            raise HistoricalAsOfError("ARCHIVED_DUPLICATE_PLAYER_FIXTURE")
        keys.add(key)
        f = fixtures.get(fixture)
        if not f or f.get("event") != gw or f.get("finished") is not True:
            raise HistoricalAsOfError("ARCHIVED_PLAYER_FIXTURE_NOT_FINAL")
        # Original event-live object key uses official element ID minus one.
        live = lives[gw].get(str(pid - 1))
        if not isinstance(live, dict) or not isinstance(live.get("stats"), dict):
            raise HistoricalAsOfError("ARCHIVED_PLAYER_EVENT_LIVE_NOT_FOUND")
        stats = live["stats"]
        if (row.get("minutes") != stats.get("minutes")
                or row.get("starts") != stats.get("starts")
                or row.get("fpl_points") != stats.get("total_points")
                or row.get("starter") is not (stats.get("starts") == 1)
                or not any(ex.get("fixture") == fixture
                           for ex in live.get("explain") or []
                           if isinstance(ex, dict))):
            raise HistoricalAsOfError("ARCHIVED_PLAYER_ROW_NOT_IN_ORIGINAL_EVENT_LIVE")
        counts[gw] += 1
    if dict(counts) != EXPECTED_GW_ROWS or len(rows) != sum(EXPECTED_GW_ROWS.values()):
        raise HistoricalAsOfError("ORIGINAL_PLAYER_MATCH_ROW_COVERAGE_INCOMPLETE")
    return {
        "contract": "V12_GW6_ORIGINAL_PREGAME_INPUT_ASOF_READBACK_V1",
        "original_run_id": ORIGINAL_RUN_ID,
        "original_commit": immutable_commit_sha,
        "original_commit_at": committed.isoformat(),
        "original_source_file_sha256": _digest(source_bytes),
        "original_normalized_file_sha256": _digest(normalized_bytes),
        "source_file_sha256_readback": "PASS",
        "normalized_file_sha256_readback": "PASS",
        "prior_gws": [1, 2, 3, 4, 5],
        "verified_finished_fixtures": 50,
        "verified_original_player_match_rows": len(rows),
        "verified_rows_by_gw": {str(gw): counts[gw] for gw in range(1, 6)},
        "official_gw6_deadline": deadline.isoformat(),
        "gw6_training_input_asof": "PASS",
        "historical_gw1_gw6_complete_asof": "PARTIAL_NOT_FULL",
        "older_target_gw_provenance": "NOT_ESTABLISHED",
        "predeadline_model_prediction": "NOT_ESTABLISHED",
        "prospective_gw7_settlement": "PENDING_FUTURE_GW_RESULTS",
        "numeric_pstart_effect": "NONE",
        "new_scheduler_created": False,
    }


def _git(repo: Path, *args: str) -> bytes:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo), *args], stderr=subprocess.DEVNULL
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise HistoricalAsOfError("ORIGINAL_GIT_OBJECT_READBACK_UNAVAILABLE") from exc


def verify_from_original_git(repo: Path) -> dict[str, object]:
    commit_at = _git(repo, "show", "-s", "--format=%cI", ORIGINAL_COMMIT).decode().strip()
    def source(path: str) -> bytes:
        return _git(repo, "show", f"{ORIGINAL_COMMIT}:{path}")
    return verify_original_gw6_archive(
        source_bytes=source(SOURCE_PATH),
        normalized_bytes=source(NORMALIZED_PATH),
        catalog_bytes=source(CATALOG_PATH),
        immutable_commit_at=commit_at,
        immutable_commit_sha=ORIGINAL_COMMIT,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--git-repo", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify_from_original_git(args.git_repo)
    output = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
