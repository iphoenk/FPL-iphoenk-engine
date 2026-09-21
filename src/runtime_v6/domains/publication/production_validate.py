from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .architecture_independence_validate import validate_repository
from .identity_coverage import validate_player_identity_coverage_truth
from .registry import EXPECTED_SOURCE_IDS, dependency_layers, load_registry
from ..control_plane.runtime_control import NATURAL_LOGICAL_SLOT_SOURCE


ROOT = Path("data/v6")


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_source_activation_transition(
    manifest: dict[str, Any],
    registry: dict[str, Any],
    *,
    schedule_kind: str,
) -> str:
    current_ids = set(EXPECTED_SOURCE_IDS)
    manifest_ids = {str(source_id) for source_id in manifest.get("source_ids") or []}
    manifest_count = int(manifest.get("source_count") or 0)
    current_count = int(registry["activation"]["active_source_count"])

    if manifest_count == current_count and manifest_ids == current_ids:
        return "CURRENT"

    # Report-prefetch intentionally hydrates the last-good factual snapshot rather
    # than running core acquisition. During a one-way activation-policy transition,
    # that hydrated snapshot can still contain sources that have just been demoted to
    # reference-only on main. Permit only that exact safe superset transition.
    if schedule_kind != "report_prefetch":
        raise AssertionError(
            f"V6 active-source mismatch outside report-prefetch: manifest={manifest_count}/{sorted(manifest_ids)!r} "
            f"registry={current_count}/{sorted(current_ids)!r}"
        )

    reference_only = set(registry["activation"].get("reference_only_sources") or {})
    disabled = set(registry["activation"].get("disabled_sources") or {})
    removed_ids = manifest_ids - current_ids
    missing_current_ids = current_ids - manifest_ids

    assert not missing_current_ids, (
        "report-prefetch hydrated snapshot is missing current active sources: "
        f"{sorted(missing_current_ids)!r}"
    )
    assert removed_ids, "report-prefetch activation transition must remove at least one source"
    assert removed_ids <= reference_only, (
        "report-prefetch may only bridge sources newly demoted to reference-only; "
        f"unexpected={sorted(removed_ids - reference_only)!r}"
    )
    assert not (removed_ids & disabled), (
        "report-prefetch must not carry disabled sources through activation transition: "
        f"{sorted(removed_ids & disabled)!r}"
    )
    assert manifest_count == len(manifest_ids), "manifest source_count/source_ids mismatch"
    return "LEGACY_ACTIVE_SUPERSET_REFERENCE_ONLY_TRANSITION"


def validate_preflight() -> dict[str, Any]:
    architecture_failures = validate_repository()
    assert architecture_failures == [], architecture_failures
    registry = load_registry()
    assert registry["engine"] == "V6_FRESH_DATA_PLATFORM"
    assert registry["policy"]["data_only"] is True
    assert registry["policy"]["decision_authority"] == "NONE"
    assert registry["policy"]["prediction_authority"] == "NONE"
    assert registry["policy"]["optimizer_authority"] == "NONE"
    assert registry["override_lifecycle"]["role"] == "TEMPORARY_REPAIR_ONLY"
    assert registry["override_lifecycle"]["inactive_source_overrides"] == []
    layers = dependency_layers(registry)
    assert layers
    return {
        "active_sources": registry["activation"]["active_source_count"],
        "active_overrides": registry["override_lifecycle"]["active_override_count"],
        "dependency_layers": layers,
    }


def validate_publishable(root: Path = ROOT) -> dict[str, Any]:
    manifest = _load(root / "manifest.json")
    integrity = _load(root / "health" / "publish_integrity.json")
    identity = _load(root / "evidence" / "player_identity_map.json")
    coverage_path = root / "evidence" / "player_identity_coverage.json"
    coverage = _load(coverage_path) if coverage_path.is_file() else None
    registry = load_registry()
    control = manifest["runtime_control"]
    event_name = os.environ["GITHUB_EVENT_NAME"]
    schedule_kind = os.environ["V6_SCHEDULE_KIND"]

    activation_transition = _validate_source_activation_transition(
        manifest,
        registry,
        schedule_kind=schedule_kind,
    )
    assert manifest["activation"]["required_active_sources"] == registry["activation"]["required_active_sources"]
    assert registry["override_lifecycle"]["inactive_source_overrides"] == []
    governance = manifest["governance"]
    assert governance["data_only"] is True
    assert governance["decision_authority"] == "NONE"
    assert governance["weather_direct_xpts_multiplier"] is False
    assert governance["production_authoritative_snapshots_require_schedule"] is False
    assert governance["production_authoritative_snapshots_require_governed_trigger"] is True
    assert governance["master_orchestrated_is_authoritative"] is True
    assert governance["report_prefetch_is_authoritative"] is True
    assert governance["report_prefetch_completes_core_operational_slot"] is False
    assert governance["manual_recovery_is_authoritative"] is False
    assert governance["single_logical_acquisition_per_scheduler_slot"] is True
    assert governance["publish_integrity_required"] is True
    assert governance["identity_mapping_is_deterministic_only"] is True
    assert governance["fuzzy_identity_matching"] is False
    assert identity["governance"]["fuzzy_name_matching_allowed"] is False
    assert integrity["status"] == "PASS", integrity
    assert integrity["current_source_files_exact"] is True
    assert integrity["resolved_registry_exact"] is True
    assert integrity["identity_map_consistent"] is True
    assert control["event_name"] == event_name
    assert control["schedule_kind"] == schedule_kind

    identity_coverage_transition = "VALIDATED"
    if coverage is None:
        # A report-prefetch can temporarily hydrate the last pre-Wave-A snapshot before
        # the next natural acquisition has produced the new coverage artifact. Do not
        # break a report slot solely for that one-way migration window.
        assert schedule_kind == "report_prefetch", "player_identity_coverage artifact missing"
        identity_coverage_transition = "LEGACY_REPORT_PREFETCH_SNAPSHOT"
    else:
        coverage_errors = validate_player_identity_coverage_truth(coverage, identity)
        assert coverage_errors == [], coverage_errors
        assert coverage["integrity_status"] == "PASS"
        assert coverage["canonical_player_count"] == identity["canonical_player_count"]
        assert governance["identity_coverage_uses_separate_canonical_and_observed_join_metrics"] is True
        assert manifest["paths"]["player_identity_coverage"] == "data/v6/evidence/player_identity_coverage.json"

    if schedule_kind == "report_prefetch":
        _validate_report_prefetch(root, control)
    elif event_name in {"issue_comment", "issues"} and schedule_kind == "chatgpt_scheduler":
        _validate_chatgpt_scheduler(manifest, control)
    elif event_name == "workflow_dispatch" and schedule_kind == "master_orchestrated":
        assert control["scheduled_cycle"] is False
        assert control["master_orchestrated"] is True
        assert control["authoritative_runtime_snapshot"] is True
        assert control["counts_as_completed_operational_slot"] is True
        assert control["manual_recovery"] is False
        assert "NON_AUTHORITATIVE_MANUAL_RECOVERY" not in manifest["control_failures"]
    elif (
        event_name in {"workflow_dispatch", "issue_comment"}
        and schedule_kind == "manual_recovery"
    ):
        assert control["scheduled_cycle"] is False
        assert control["authoritative_runtime_snapshot"] is False
        assert control["counts_as_completed_operational_slot"] is False
        assert control["counts_as_completed_scheduled_slot"] is False
        assert control["manual_recovery"] is True
        assert (
            "NON_AUTHORITATIVE_MANUAL_RECOVERY"
            in manifest["control_failures"]
        )
    else:
        raise AssertionError(f"unexpected V6 production event: {event_name}/{schedule_kind}")

    return {
        "overall": manifest["overall"],
        "runtime_control": control,
        "publish_integrity": integrity,
        "identity_coverage_transition": identity_coverage_transition,
        "activation_transition": activation_transition,
    }


def _validate_report_prefetch(root: Path, control: dict[str, Any]) -> None:
    assert control["authoritative_runtime_snapshot"] is True
    assert control["report_prefetch"] is True
    assert control["counts_as_completed_report_slot"] is True
    assert control["counts_as_completed_operational_slot"] is False
    report_kind = os.environ["V6_PREFETCH_REPORT_KIND"]
    if report_kind == "historical_backfill":
        history = _load(root / "health" / "historical_backfill.json")
        assert history["report_kind"] == "historical_backfill"
        assert history["scope"] == "mini_league"
        assert history["gw_from"] == int(os.environ["V6_PREFETCH_GW_FROM"])
        assert history["gw_to"] == int(os.environ["V6_PREFETCH_GW_TO"])
        assert history["cohort_semantics"] == "CURRENT_COHORT_HISTORY"
        for key in (
            "decision_authority",
            "prediction_authority",
            "optimizer_authority",
            "bayesian_authority",
            "monte_carlo_authority",
        ):
            assert history["governance"][key] == "NONE"
        assert history["governance"]["data_only"] is True
        assert history["overall_status"] in {"GREEN", "AMBER"}
        return

    prefetch = _load(root / "report_prefetch" / "latest.json")
    health = _load(root / "health" / "report_prefetch.json")
    assert prefetch["report_kind"] == report_kind
    assert prefetch["target_logical_report_slot"] == os.environ["V6_PREFETCH_LOGICAL_SLOT"]
    assert prefetch["governance"]["data_only"] is True
    for key in ("decision_authority", "prediction_authority", "optimizer_authority"):
        assert prefetch["governance"][key] == "NONE"
    assert prefetch["governance"]["independent_prefetch_cron"] is False
    assert health["fresh_for_target_report"] == prefetch["fresh_for_target_report"]
    if report_kind == "05:30_price":
        # Price report is deliberately narrow: no unrelated authenticated personal
        # refresh, but Official price/bootstrap + mini-league factual retrieval must
        # actually be attempted so price-impact/frontier analysis has fresh inputs.
        assert prefetch["personal_requested"] is False
        assert prefetch["mini_league_requested"] is True
        assert prefetch["live_requested"] is False
        assert prefetch["auth_state"] == "NOT_REQUESTED"
        assert prefetch["telemetry"]["request_count"] > 0
        assert prefetch["governance"]["price_0530_requires_mini_league_facts"] is True


def _validate_chatgpt_scheduler(manifest: dict[str, Any], control: dict[str, Any]) -> None:
    requested = datetime.fromisoformat(os.environ["V6_MASTER_LOGICAL_SLOT"]).astimezone(timezone.utc)
    assert control["chatgpt_scheduler"] is True
    assert control["chatgpt_scheduler_proof"] is True
    assert control["scheduled_cycle"] is True
    assert control["master_orchestrated"] is True
    assert control["authoritative_runtime_snapshot"] is True
    assert control["counts_as_completed_operational_slot"] is True
    assert control["logical_slot_source"] == NATURAL_LOGICAL_SLOT_SOURCE
    assert control["expected_cycle_at"] == requested.isoformat()
    assert manifest["governance"]["production_ingestion_schedule_only"] is False
    assert manifest["governance"]["chatgpt_scheduler_is_authority"] is True


def main() -> int:
    parser = argparse.ArgumentParser(description="V6 production validation")
    parser.add_argument("command", choices=["preflight", "publishable"])
    args = parser.parse_args()
    result = validate_preflight() if args.command == "preflight" else validate_publishable()
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
