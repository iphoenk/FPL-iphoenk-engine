from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.v5 import V5_VERSION
from src.v5.release_integrity import runtime_fingerprint


def git(*args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", *args], check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc.stdout.strip()


def parse_dt(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def load_remote_json(ref: str, path: str, default: dict | None = None) -> dict:
    proc = subprocess.run(["git", "show", f"{ref}:{path}"], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if proc.returncode != 0:
        return dict(default or {})
    payload = json.loads(proc.stdout)
    return payload if isinstance(payload, dict) else dict(default or {})


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def operational_revalidation_reasons(
    summary: dict,
    *,
    deployed_runtime_sha: str,
    current_release_fingerprint: str,
    current_v5_version: str,
    required_cycles: int,
) -> list[str]:
    """Return fail-closed reasons that require fresh REAL_SHADOW evidence."""
    if not isinstance(summary, dict) or not summary:
        return ["OPERATIONAL_ACCEPTANCE_MISSING"]

    reasons: list[str] = []
    if str(summary.get("production_main_sha") or "").lower() != deployed_runtime_sha.lower():
        reasons.append("PRODUCTION_REANCHOR_REVALIDATION")

    if (
        str(summary.get("release_fingerprint") or "") != current_release_fingerprint
        or str(summary.get("v5_version") or "") != current_v5_version
    ):
        reasons.append("V5_RELEASE_REVALIDATION")

    declared_required = _int(summary.get("required_validated_cycles"), -1)
    validated = _int(summary.get("validated_successful_cycles"), 0)
    if declared_required != required_cycles:
        reasons.append("OPERATIONAL_ACCEPTANCE_POLICY_DRIFT")
    if validated < required_cycles or summary.get("operational_candidate_eligible") is not True:
        reasons.append("OPERATIONAL_ACCEPTANCE_INCOMPLETE")

    return sorted(set(reasons))


def evaluate(event_name: str) -> tuple[bool, list[str], dict, datetime]:
    v3_runtime_branch = os.environ.get("V3_RUNTIME_BRANCH", "runtime-data")
    v5_shadow_branch = os.environ.get("V5_SHADOW_BRANCH", "v5-shadow-runtime")
    tz_authority = os.environ.get("TZ_AUTHORITY", "Asia/Jakarta")
    git("fetch", "origin", "main", v3_runtime_branch, v5_shadow_branch)

    now = datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo(tz_authority))
    ledger = load_remote_json(f"origin/{v5_shadow_branch}", "data/v5/prediction_ledger.json", {"records": {}})
    records = ledger.get("records") if isinstance(ledger.get("records"), dict) else {}
    manifest = json.loads(Path("config/v5_convergence_manifest.json").read_text(encoding="utf-8"))
    parity = json.loads(Path("config/v5_shadow_parity_registry.json").read_text(encoding="utf-8"))
    authority = str((manifest.get("baselines") or {}).get("production_source_authority") or "")
    repository_main_sha = git("rev-parse", "origin/main")
    runtime_manifest = load_remote_json(f"origin/{v3_runtime_branch}", "data/runtime_manifest.json")
    deployed_runtime_sha = str(runtime_manifest.get("source_commit") or "").lower()
    sha_valid = bool(re.fullmatch(r"[0-9a-f]{40}", deployed_runtime_sha))
    ancestor_ok = sha_valid and subprocess.run(
        ["git", "merge-base", "--is-ancestor", deployed_runtime_sha, "origin/main"],
        check=False,
    ).returncode == 0
    baseline_ready = bool(authority == "runtime-data:data/runtime_manifest.json#source_commit" and sha_valid and ancestor_ok)
    required_cycles = max(1, _int(parity.get("required_cycles_before_production_candidate"), 3))
    current_release_fingerprint = str(runtime_fingerprint()["fingerprint"])
    acceptance_summary = load_remote_json(
        f"origin/{v5_shadow_branch}",
        "data/v5/shadow/acceptance_summary.json",
        {},
    )
    revalidation_reasons = operational_revalidation_reasons(
        acceptance_summary,
        deployed_runtime_sha=deployed_runtime_sha,
        current_release_fingerprint=current_release_fingerprint,
        current_v5_version=V5_VERSION,
        required_cycles=required_cycles,
    ) if baseline_ready else []

    details = {
        "production_source_authority": authority,
        "deployed_runtime_sha": deployed_runtime_sha,
        "repository_main_sha": repository_main_sha,
        "deployed_runtime_is_ancestor_of_main": ancestor_ok,
        "baseline_ready": baseline_ready,
        "current_v5_version": V5_VERSION,
        "current_release_fingerprint": current_release_fingerprint,
        "required_operational_cycles": required_cycles,
        "acceptance_summary_present": bool(acceptance_summary),
        "acceptance_production_sha": str(acceptance_summary.get("production_main_sha") or ""),
        "acceptance_release_fingerprint": str(acceptance_summary.get("release_fingerprint") or ""),
        "acceptance_validated_cycles": _int(acceptance_summary.get("validated_successful_cycles"), 0),
        "acceptance_operational_eligible": acceptance_summary.get("operational_candidate_eligible") is True,
        "operational_revalidation_required": bool(revalidation_reasons),
    }
    reasons: list[str] = []
    if not baseline_ready:
        details["blocked_reason"] = "DEPLOYED_PRODUCTION_BASELINE_NOT_RECONCILED"
        return False, reasons, details, local

    reasons.extend(revalidation_reasons)
    if event_name == "workflow_dispatch":
        reasons.append("MANUAL_SCHEDULER_DISPATCH")
    if local.hour == 4:
        reasons.append("DAILY_0430_WIB_EVIDENCE_REFRESH")

    # Revalidation/manual/daily reasons already justify a governed cycle. Avoid an extra
    # Official bootstrap request when the heavy shadow cycle is going to fetch fresh truth anyway.
    reasons = sorted(set(reasons))
    if reasons:
        return True, reasons, details, local

    req = urllib.request.Request(
        "https://fantasy.premierleague.com/api/bootstrap-static/",
        headers={"User-Agent": "fpl-iphoenk-v5-evidence-scheduler/2.1"},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        bootstrap = json.load(response)
    events = [row for row in bootstrap.get("events") or [] if isinstance(row, dict)]

    future, passed_unfinished, finished_ids = [], [], set()
    for event in events:
        gw = int(event.get("id") or 0)
        deadline = parse_dt(event.get("deadline_time"))
        if event.get("finished") is True:
            finished_ids.add(gw)
        if deadline is None:
            continue
        if deadline > now:
            future.append((deadline, gw))
        elif event.get("finished") is not True:
            passed_unfinished.append((deadline, gw))

    if future:
        next_deadline, next_gw = min(future)
        hours_to_deadline = (next_deadline - now).total_seconds() / 3600.0
        details["next_gw"] = next_gw
        details["hours_to_deadline"] = round(hours_to_deadline, 2)
        if 0 < hours_to_deadline <= 24:
            reasons.append(f"DEADLINE_WINDOW_GW{next_gw}_T24H")

    if passed_unfinished:
        last_deadline, live_gw = max(passed_unfinished)
        hours_since_deadline = (now - last_deadline).total_seconds() / 3600.0
        details["active_postdeadline_gw"] = live_gw
        details["hours_since_deadline"] = round(hours_since_deadline, 2)
        if 0 <= hours_since_deadline <= 6:
            reasons.append(f"POSTDEADLINE_FREEZE_GUARD_GW{live_gw}")
        elif local.hour % 3 == 0:
            reasons.append(f"MATCH_MODE_3H_GW{live_gw}")

    for key, record in records.items():
        if not isinstance(record, dict):
            continue
        try:
            gw = int(record.get("gw") or key)
        except (TypeError, ValueError):
            continue
        if record.get("status") == "SETTLED":
            continue
        deadline = parse_dt(record.get("deadline_time"))
        if deadline and deadline <= now and not isinstance(record.get("frozen_forecast"), dict):
            candidate = record.get("latest_pre_deadline_forecast")
            generated = parse_dt((candidate or {}).get("generated_at")) if isinstance(candidate, dict) else None
            if candidate and generated and generated <= deadline:
                reasons.append(f"FREEZE_RECOVERY_PENDING_GW{gw}")
        if gw in finished_ids and isinstance(record.get("frozen_forecast"), dict):
            reasons.append(f"SETTLEMENT_PENDING_GW{gw}")

    reasons = sorted(set(reasons))
    return bool(reasons), reasons, details, local


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME", ""))
    args = parser.parse_args()
    should_run, reasons, details, local = evaluate(args.event_name)
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"should_run={'true' if should_run else 'false'}\n")
            handle.write(f"baseline_ready={'true' if details.get('baseline_ready') else 'false'}\n")
            handle.write(f"reason_count={len(reasons)}\n")
            handle.write("reasons=" + ",".join(reasons) + "\n")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        Path(summary_path).write_text(
            "# V5 Evidence Scheduler\n\n"
            f"- Time authority: `{local.isoformat()}`\n"
            f"- Deployed baseline ready: **{details.get('baseline_ready')}**\n"
            f"- Operational revalidation required: **{details.get('operational_revalidation_required')}**\n"
            f"- Scheduled heavy cycle: **{should_run}**\n"
            f"- Reasons: `{', '.join(reasons) if reasons else 'NONE'}`\n"
            f"- Details: `{json.dumps(details, sort_keys=True)}`\n",
            encoding="utf-8",
        )
    print(json.dumps({"should_run": should_run, "reasons": reasons, "details": details, "local_time": local.isoformat()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
