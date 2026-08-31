from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD_SHA = "ef0161113a763306419c0c367770e6dcfe6570d1"
NEW_SHA = "d7fc5dfda0b3522f8b32bcb726d70a86e9fedd87"
EVIDENCE_AUTHORITY = "v5-shadow-runtime:data/v5/shadow/acceptance_summary.json"


def load_json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def write_json(path: str, payload: dict) -> None:
    (ROOT / path).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def replace_sha(value):
    if isinstance(value, dict):
        return {k: replace_sha(v) for k, v in value.items()}
    if isinstance(value, list):
        return [replace_sha(v) for v in value]
    if isinstance(value, str):
        return value.replace(OLD_SHA, NEW_SHA)
    return value


def patch_metadata() -> None:
    manifest = replace_sha(load_json("config/v5_convergence_manifest.json"))
    manifest["baselines"]["production_main_sha"] = NEW_SHA
    manifest["baselines"]["production_code_commit"] = NEW_SHA
    evidence = manifest["operational_acceptance_evidence"]
    evidence["authority"] = EVIDENCE_AUTHORITY
    evidence["materialized_status_snapshot_only"] = True
    evidence["status"] = "SUPERSEDED_BY_PRODUCTION_REANCHOR_PENDING_REVALIDATION"
    evidence["release_fingerprint"] = None
    evidence["validated_real_shadow_cycles"] = 0
    evidence["remaining_validated_cycles"] = int(evidence.get("required_real_shadow_cycles") or 3)
    evidence["operational_candidate_eligible"] = False
    evidence["prediction_candidate_eligible"] = False
    evidence["production_candidate_eligible"] = False
    evidence["note"] = (
        f"Runtime acceptance authority is {EVIDENCE_AUTHORITY}. Static counters here are a materialized governance snapshot only. "
        f"Three fresh exact-fingerprint postvalidated REAL_SHADOW cycles are required against deployed production {NEW_SHA}."
    )
    promotion = manifest["production_promotion"]
    promotion["operational_evidence_authority"] = EVIDENCE_AUTHORITY
    promotion["materialized_status_snapshot_only"] = True
    promotion["allowed"] = False
    promotion["production_candidate"] = False
    promotion["validated_real_shadow_cycles"] = 0
    promotion["operational_acceptance_complete"] = False
    promotion["prediction_acceptance_complete"] = False
    promotion["reason"] = (
        "Production source reanchor invalidates static release attestation and requires fresh runtime evidence. "
        f"Operational truth is read from {EVIDENCE_AUTHORITY}; prediction acceptance remains independent and mandatory."
    )
    manifest["advanced_v5"]["runtime_acceptance_summary_is_single_evidence_authority"] = True
    write_json("config/v5_convergence_manifest.json", manifest)

    acceptance = replace_sha(load_json("config/v5_acceptance_registry.json"))
    acceptance["version"] = int(acceptance.get("version") or 0) + 1
    acceptance["convergence"]["production_main_sha"] = NEW_SHA
    acceptance["convergence"]["production_code_commit"] = NEW_SHA
    acceptance["convergence"]["operational_acceptance_evidence_authority"] = EVIDENCE_AUTHORITY
    acceptance["convergence"]["static_acceptance_counters_must_not_be_runtime_authority"] = True
    write_json("config/v5_acceptance_registry.json", acceptance)

    parity = replace_sha(load_json("config/v5_capability_parity_registry.json"))
    parity["schema_version"] = int(parity.get("schema_version") or 0) + 1
    parity["authorities"]["current_production_runtime"] = f"deployed@{NEW_SHA}"
    parity["authorities"]["current_production_code_commit"] = NEW_SHA
    parity["current_production_reanchor"]["production_main_sha"] = NEW_SHA
    parity["current_production_reanchor"]["production_code_commit"] = NEW_SHA
    parity.setdefault("governance", {})["operational_acceptance_evidence_authority"] = EVIDENCE_AUTHORITY
    parity["governance"]["static_acceptance_metadata_is_not_runtime_evidence_authority"] = True
    write_json("config/v5_capability_parity_registry.json", parity)

    status = replace_sha(load_json("IMPLEMENTATION_STATUS.json"))
    status["production_authority"]["main_sha"] = NEW_SHA
    status["state"] = "ADVANCED_BETA4_PRODUCTION_REANCHOR_OPERATIONAL_REVALIDATION_PENDING"
    status["acceptance"]["authority"] = EVIDENCE_AUTHORITY
    status["acceptance"]["materialized_status_snapshot_only"] = True
    status["acceptance"]["fresh_postvalidated_real_shadow_cycles"] = 0
    status["acceptance"]["operational_candidate_eligible"] = False
    status["acceptance"]["prediction_candidate_eligible"] = False
    status["acceptance"]["production_candidate_eligible"] = False
    status["acceptance"]["production_promotion_allowed"] = False
    status.setdefault("notes", []).append(
        f"Operational acceptance counters in static metadata are non-authoritative snapshots; the single runtime evidence authority is {EVIDENCE_AUTHORITY}."
    )
    write_json("IMPLEMENTATION_STATUS.json", status)


def patch_metadata_test() -> None:
    path = ROOT / "tests/test_v5_metadata_authority_hygiene.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace(f'DEPLOYED_SHA = "{OLD_SHA}"', f'DEPLOYED_SHA = "{NEW_SHA}"')
    marker = "STALE_DEPLOYED_SHAS = {\n"
    if OLD_SHA not in text.split(marker, 1)[1].split("}", 1)[0]:
        text = text.replace(marker, marker + f'    "{OLD_SHA}",\n', 1)
    path.write_text(text, encoding="utf-8")


def patch_on_demand_workflow() -> None:
    path = ROOT / ".github/workflows/v5-on-demand-report.yml"
    text = path.read_text(encoding="utf-8")
    old = '''      - name: Resolve current production authority\n        shell: bash\n        run: |\n          set -euo pipefail\n          git fetch origin "$PRODUCTION_SOURCE_BRANCH" "$PRODUCTION_RUNTIME_BRANCH"\n          SOURCE_SHA=$(git rev-parse "origin/$PRODUCTION_SOURCE_BRANCH")\n          echo "PRODUCTION_SOURCE_SHA=$SOURCE_SHA" >> "$GITHUB_ENV"\n          echo "production_source=$PRODUCTION_SOURCE_BRANCH sha=$SOURCE_SHA"\n'''
    new = '''      - name: Resolve deployed production authority\n        shell: bash\n        run: |\n          set -euo pipefail\n          git fetch origin "$PRODUCTION_SOURCE_BRANCH" "$PRODUCTION_RUNTIME_BRANCH"\n          MAIN_HEAD=$(git rev-parse "origin/$PRODUCTION_SOURCE_BRANCH")\n          RUNTIME_MANIFEST=$(git show "origin/${PRODUCTION_RUNTIME_BRANCH}:data/runtime_manifest.json")\n          SOURCE_SHA=$(printf '%s' "$RUNTIME_MANIFEST" | python -c "import json,sys; print(json.load(sys.stdin)['source_commit'])")\n          test -n "$SOURCE_SHA"\n          git cat-file -e "${SOURCE_SHA}^{commit}"\n          git merge-base --is-ancestor "$SOURCE_SHA" "origin/$PRODUCTION_SOURCE_BRANCH"\n          echo "PRODUCTION_SOURCE_SHA=$SOURCE_SHA" >> "$GITHUB_ENV"\n          echo "production_runtime_source=$SOURCE_SHA repository_main=$MAIN_HEAD"\n'''
    if old not in text:
        raise RuntimeError("on-demand production authority block drifted")
    text = text.replace(old, new, 1)

    old_hydrate = '''          mkdir -p "$prod_tree/data/stats"\n          for file in price_cache.json price_trajectory.json rules_source_state.json prediction_ledger.json challenger_observations.json report_state.json dss_watchlist.json; do\n            if git cat-file -e "origin/${PRODUCTION_RUNTIME_BRANCH}:data/${file}" 2>/dev/null; then\n              git show "origin/${PRODUCTION_RUNTIME_BRANCH}:data/${file}" > "$prod_tree/data/${file}"\n            fi\n          done\n          for stat_file in vaastav_previous_season.json shots_gw1.json playermatchstats_gw1.json core_insights_gw1.json; do\n            if git cat-file -e "origin/${PRODUCTION_RUNTIME_BRANCH}:data/stats/${stat_file}" 2>/dev/null; then\n              git show "origin/${PRODUCTION_RUNTIME_BRANCH}:data/stats/${stat_file}" > "$prod_tree/data/stats/${stat_file}"\n            fi\n          done\n'''
    new_hydrate = '''          git show "$PRODUCTION_SOURCE_SHA:config/runtime/runtime_publish_registry.json" > "$RUNNER_TEMP/runtime_publish_registry.json"\n          python - <<'PY' > "$RUNNER_TEMP/hydrate-paths.txt"\n          import json, os\n          cfg=json.load(open(os.path.join(os.environ['RUNNER_TEMP'], 'runtime_publish_registry.json')))\n          for path in cfg.get('hydrate_paths', []):\n              print(path)\n          PY\n          while IFS= read -r file; do\n            [ -n "$file" ] || continue\n            if git cat-file -e "origin/${PRODUCTION_RUNTIME_BRANCH}:data/${file}" 2>/dev/null; then\n              mkdir -p "$prod_tree/data/$(dirname "$file")"\n              git show "origin/${PRODUCTION_RUNTIME_BRANCH}:data/${file}" > "$prod_tree/data/${file}"\n            fi\n          done < "$RUNNER_TEMP/hydrate-paths.txt"\n'''
    if old_hydrate not in text:
        raise RuntimeError("on-demand hydration block drifted")
    text = text.replace(old_hydrate, new_hydrate, 1)
    path.write_text(text, encoding="utf-8")


def write_scheduler_scripts() -> None:
    gate = r'''from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


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
    expected_runtime_sha = str((manifest.get("baselines") or {}).get("production_main_sha") or "")
    repository_main_sha = git("rev-parse", "origin/main")
    runtime_manifest = load_remote_json(f"origin/{v3_runtime_branch}", "data/runtime_manifest.json")
    deployed_runtime_sha = str(runtime_manifest.get("source_commit") or "")
    ancestor_ok = bool(expected_runtime_sha) and subprocess.run(
        ["git", "merge-base", "--is-ancestor", expected_runtime_sha, "origin/main"],
        check=False,
    ).returncode == 0
    baseline_ready = bool(expected_runtime_sha and expected_runtime_sha == deployed_runtime_sha and ancestor_ok)
    details = {
        "accepted_deployed_runtime_sha": expected_runtime_sha,
        "deployed_runtime_sha": deployed_runtime_sha,
        "repository_main_sha": repository_main_sha,
        "accepted_runtime_is_ancestor_of_main": ancestor_ok,
        "baseline_ready": baseline_ready,
    }
    reasons: list[str] = []
    if not baseline_ready:
        details["blocked_reason"] = "DEPLOYED_PRODUCTION_BASELINE_NOT_RECONCILED"
        return False, reasons, details, local

    req = urllib.request.Request(
        "https://fantasy.premierleague.com/api/bootstrap-static/",
        headers={"User-Agent": "fpl-iphoenk-v5-evidence-scheduler/2.0"},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        bootstrap = json.load(response)
    events = [row for row in bootstrap.get("events") or [] if isinstance(row, dict)]

    if event_name == "workflow_dispatch":
        reasons.append("MANUAL_SCHEDULER_DISPATCH")
    if local.hour == 4:
        reasons.append("DAILY_0430_WIB_EVIDENCE_REFRESH")

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
            f"- Scheduled heavy cycle: **{should_run}**\n"
            f"- Reasons: `{', '.join(reasons) if reasons else 'NONE'}`\n"
            f"- Details: `{json.dumps(details, sort_keys=True)}`\n",
            encoding="utf-8",
        )
    print(json.dumps({"should_run": should_run, "reasons": reasons, "details": details, "local_time": local.isoformat()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
    (ROOT / "scripts/v5_evidence_scheduler_gate.py").write_text(gate, encoding="utf-8")

    dispatch = r'''from __future__ import annotations

import argparse
import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


def request_json(url: str, *, token: str, method: str = "GET", payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else {}


def dispatch(repo: str, branch: str, token: str, reasons: list[str]) -> dict:
    path = "config/v5_shadow_trigger.json"
    encoded_path = urllib.parse.quote(path, safe="/")
    base = f"https://api.github.com/repos/{repo}/contents/{encoded_path}"
    for attempt in range(1, 4):
        current = request_json(f"{base}?ref={urllib.parse.quote(branch, safe='')}", token=token)
        content = json.loads(base64.b64decode(current["content"]).decode("utf-8"))
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        run_id = os.environ.get("GITHUB_RUN_ID", "local")
        content["requested_cycle"] = f"scheduler-{run_id}-{int(time.time())}"
        content["requested_at"] = now
        content["scheduler_reasons"] = reasons
        content["scheduler_source"] = "default-branch-thin-dispatcher"
        payload = {
            "message": f"chore(v5): dispatch governed shadow evidence [{','.join(reasons) or 'manual'}]",
            "content": base64.b64encode((json.dumps(content, indent=2, ensure_ascii=False) + "\n").encode("utf-8")).decode("ascii"),
            "sha": current["sha"],
            "branch": branch,
        }
        try:
            return request_json(base, token=token, method="PUT", payload=payload)
        except urllib.error.HTTPError as exc:
            if exc.code not in {409, 422} or attempt >= 3:
                raise
            time.sleep(attempt)
    raise RuntimeError("unable to dispatch V5 shadow trigger")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reasons", default="")
    parser.add_argument("--branch", default=os.environ.get("V5_CODE_BRANCH", "v5-unified-engine"))
    args = parser.parse_args()
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    reasons = [row for row in args.reasons.split(",") if row]
    result = dispatch(repo, args.branch, token, reasons)
    print(json.dumps({"commit": (result.get("commit") or {}).get("sha"), "branch": args.branch, "reasons": reasons}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
    (ROOT / "scripts/v5_dispatch_shadow_trigger.py").write_text(dispatch, encoding="utf-8")


def patch_scheduler_workflow() -> None:
    workflow = '''name: V5 Evidence Scheduler Manual Gate\n\non:\n  workflow_dispatch:\n\n# Scheduled authority lives on the default branch as a thin dispatcher.\n# This workflow remains a manual diagnostic entrypoint and executes the same governed gate script.\npermissions:\n  contents: write\n\nconcurrency:\n  group: v5-evidence-scheduler\n  cancel-in-progress: true\n\nenv:\n  V5_SHADOW_BRANCH: v5-shadow-runtime\n  V3_RUNTIME_BRANCH: runtime-data\n  V5_CODE_BRANCH: v5-unified-engine\n  TZ_AUTHORITY: Asia/Jakarta\n\njobs:\n  evidence-gate:\n    runs-on: ubuntu-latest\n    timeout-minutes: 5\n    steps:\n      - name: Checkout V5 scheduler authority\n        uses: actions/checkout@v4\n        with:\n          ref: v5-unified-engine\n          fetch-depth: 0\n\n      - name: Evaluate governed evidence window\n        id: gate\n        run: python scripts/v5_evidence_scheduler_gate.py --event-name workflow_dispatch\n\n      - name: Trigger governed V5 shadow evidence cycle\n        if: steps.gate.outputs.should_run == 'true'\n        env:\n          GITHUB_TOKEN: ${{ github.token }}\n        run: python scripts/v5_dispatch_shadow_trigger.py --reasons "${{ steps.gate.outputs.reasons }}"\n\n      - name: No-op outside governed evidence windows or during baseline drift\n        if: steps.gate.outputs.should_run != 'true'\n        run: echo "No heavy V5 cycle required; either outside evidence window or deployed production baseline is not reconciled."\n'''
    (ROOT / ".github/workflows/v5-evidence-scheduler.yml").write_text(workflow, encoding="utf-8")


def write_tests() -> None:
    test = r'''import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_AUTHORITY = "v5-shadow-runtime:data/v5/shadow/acceptance_summary.json"


def _load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_runtime_acceptance_has_one_declared_evidence_authority():
    manifest = _load("config/v5_convergence_manifest.json")
    acceptance = _load("config/v5_acceptance_registry.json")
    parity = _load("config/v5_capability_parity_registry.json")
    status = _load("IMPLEMENTATION_STATUS.json")
    assert manifest["operational_acceptance_evidence"]["authority"] == EVIDENCE_AUTHORITY
    assert manifest["operational_acceptance_evidence"]["materialized_status_snapshot_only"] is True
    assert manifest["production_promotion"]["operational_evidence_authority"] == EVIDENCE_AUTHORITY
    assert manifest["production_promotion"]["materialized_status_snapshot_only"] is True
    assert acceptance["convergence"]["operational_acceptance_evidence_authority"] == EVIDENCE_AUTHORITY
    assert acceptance["convergence"]["static_acceptance_counters_must_not_be_runtime_authority"] is True
    assert parity["governance"]["operational_acceptance_evidence_authority"] == EVIDENCE_AUTHORITY
    assert status["acceptance"]["authority"] == EVIDENCE_AUTHORITY
    assert status["acceptance"]["materialized_status_snapshot_only"] is True


def test_on_demand_uses_deployed_runtime_source_and_registry_hydration():
    source = (ROOT / ".github/workflows/v5-on-demand-report.yml").read_text(encoding="utf-8")
    assert "data/runtime_manifest.json" in source
    assert "['source_commit']" in source
    assert 'git merge-base --is-ancestor "$SOURCE_SHA"' in source
    assert "runtime_publish_registry.json" in source
    assert "hydrate_paths" in source
    assert 'SOURCE_SHA=$(git rev-parse "origin/$PRODUCTION_SOURCE_BRANCH")' not in source
    assert "for file in price_cache.json" not in source
    assert "for stat_file in" not in source


def test_v5_branch_scheduler_has_no_dead_cron_and_delegates_policy_to_script():
    workflow = (ROOT / ".github/workflows/v5-evidence-scheduler.yml").read_text(encoding="utf-8")
    gate = (ROOT / "scripts/v5_evidence_scheduler_gate.py").read_text(encoding="utf-8")
    dispatch = (ROOT / "scripts/v5_dispatch_shadow_trigger.py").read_text(encoding="utf-8")
    assert "  schedule:" not in workflow
    assert "v5_evidence_scheduler_gate.py" in workflow
    assert "v5_dispatch_shadow_trigger.py" in workflow
    assert "production_main_sha" in gate
    assert "data/runtime_manifest.json" in gate
    assert "merge-base" in gate
    assert "config/v5_shadow_trigger.json" in dispatch
    assert "default-branch-thin-dispatcher" in dispatch
'''
    (ROOT / "tests/test_v5_control_plane_governance.py").write_text(test, encoding="utf-8")


def main() -> None:
    patch_metadata()
    patch_metadata_test()
    patch_on_demand_workflow()
    write_scheduler_scripts()
    patch_scheduler_workflow()
    write_tests()


if __name__ == "__main__":
    main()
