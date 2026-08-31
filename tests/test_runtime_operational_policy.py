from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "runtime" / "v4_operational_policy.json"
WATCHDOG_PATH = ROOT / ".github" / "scripts" / "v4_runtime_watchdog.py"
WORKFLOWS = ROOT / ".github" / "workflows"

spec = importlib.util.spec_from_file_location("runtime_operational_policy_test", WATCHDOG_PATH)
assert spec and spec.loader
watchdog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watchdog)


def _policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def test_watchdog_consumes_registry_owned_operational_thresholds() -> None:
    policy = _policy()
    assert watchdog.POLICY == policy
    assert watchdog.FRESH_MAX_MINUTES == float(policy["fresh_max_minutes"])
    assert watchdog.STALE_AFTER_MINUTES == float(policy["stale_after_minutes"])
    assert watchdog.MASTER_CHECKPOINT_MINUTE == int(policy["master_checkpoint_minute"])
    assert watchdog.MAX_REPORTED_MISSES == int(policy["max_reported_misses"])


def test_dispatcher_literals_are_guarded_against_policy_drift() -> None:
    policy = _policy()
    scheduler = (WORKFLOWS / "v4-prediction.yml").read_text(encoding="utf-8")
    recovery = (WORKFLOWS / "fpl-engine-recovery.yml").read_text(encoding="utf-8")
    timing = (WORKFLOWS / "v4-timing-probe.yml").read_text(encoding="utf-8")
    expected_group = str(policy["production_concurrency_group"])
    expected_ref = str(policy["canonical_ref"])
    expected_runtime = str(policy["runtime_branch"])
    expected_minute = int(policy["master_checkpoint_minute"])
    assert f'cron: "{expected_minute} * * * *"' in scheduler
    assert expected_group in scheduler
    assert expected_group in recovery
    assert expected_group in timing
    assert expected_ref in scheduler
    assert expected_ref in recovery
    assert expected_ref in timing
    assert expected_runtime in recovery


def test_policy_has_monotonic_freshness_contract() -> None:
    policy = _policy()
    assert policy["timezone"] == "Asia/Jakarta"
    assert 0 <= int(policy["master_checkpoint_minute"]) <= 59
    assert 0 < float(policy["fresh_max_minutes"]) < float(policy["stale_after_minutes"])
    assert int(policy["max_reported_misses"]) > 0
