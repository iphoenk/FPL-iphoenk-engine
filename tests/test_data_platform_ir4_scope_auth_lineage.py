from __future__ import annotations

from src.runtime_v6.domains.report_plane import report_prefetch


def _scope_health():
    return {
        "CORE": "GREEN",
        "REPORT_PREFETCH": "GREEN",
        "PERSONAL": "DEGRADED",
        "MINI_LEAGUE": "GREEN",
        "AUTH": "AUTH_EXPIRED",
        "ICON+": "GREEN",
    }


def test_core_green_does_not_override_required_scope_degradation():
    evaluate = getattr(report_prefetch, "evaluate_report_scope_health", None)
    assert callable(evaluate), "IR4 requires canonical scope-local health evaluation"

    result = evaluate(
        _scope_health(),
        required_scopes=("CORE", "REPORT_PREFETCH", "PERSONAL", "MINI_LEAGUE", "ICON+"),
        public_report=False,
    )

    assert result["scope_status"]["CORE"] == "GREEN"
    assert result["scope_status"]["PERSONAL"] == "DEGRADED"
    assert result["overall_status"] != "GREEN"
    assert "PERSONAL" in result["blocking_scopes"]


def test_auth_expired_is_scope_local_for_public_deep():
    evaluate = getattr(report_prefetch, "evaluate_report_scope_health", None)
    assert callable(evaluate)

    result = evaluate(
        _scope_health(),
        required_scopes=("CORE", "REPORT_PREFETCH", "MINI_LEAGUE", "ICON+"),
        public_report=True,
    )

    assert result["auth_state"] == "AUTH_EXPIRED"
    assert result["auth_blocks_public_report"] is False
    assert result["overall_status"] == "GREEN"
    assert "AUTH" not in result["blocking_scopes"]


def test_auth_states_are_explicit_and_normalized():
    normalize = getattr(report_prefetch, "normalize_report_auth_state", None)
    assert callable(normalize), "IR4 requires explicit report auth states"

    assert normalize("AUTH_AVAILABLE", requested=True) == "AUTH_OK"
    assert normalize("AUTH_EXPIRED", requested=True) == "AUTH_EXPIRED"
    assert normalize("AUTH_INVALID", requested=True) == "AUTH_FAILED"
    assert normalize("AUTH_UNAVAILABLE", requested=True) == "AUTH_FAILED"
    assert normalize(None, requested=False) == "AUTH_NOT_REQUESTED"


def test_lineage_uses_oldest_generation_and_derived_age():
    build = getattr(report_prefetch, "build_report_scope_lineage", None)
    assert callable(build), "IR4 requires canonical report lineage"

    lineage = build(
        [
            {
                "scope": "CORE",
                "generated_at": "2026-09-18T04:12:00+07:00",
                "source_run_id": "core-run-77",
                "report_prefetch_run_id": None,
            },
            {
                "scope": "REPORT_PREFETCH",
                "generated_at": "2026-09-18T04:20:00+07:00",
                "source_run_id": "core-run-77",
                "report_prefetch_run_id": "prefetch-run-88",
            },
            {
                "scope": "PERSONAL",
                "generated_at": "2026-09-18T04:18:00+07:00",
                "source_run_id": "core-run-77",
                "report_prefetch_run_id": "prefetch-run-88",
            },
        ],
        logical_slot="2026-09-18T04:30:00+07:00",
        observed_at="2026-09-18T04:30:00+07:00",
        maximum_age_minutes=35,
    )

    assert lineage["min_generated_at"] == "2026-09-18T04:12:00+07:00"
    assert lineage["age_minutes"] == 18.0
    assert lineage["source_run_id"] == "core-run-77"
    assert lineage["report_prefetch_run_id"] == "prefetch-run-88"
    assert lineage["logical_slot"] == "2026-09-18T04:30:00+07:00"
    assert lineage["freshness_status"] == "CURRENT"


def test_cross_generation_mix_is_blocked():
    build = getattr(report_prefetch, "build_report_scope_lineage", None)
    assert callable(build)

    lineage = build(
        [
            {
                "scope": "REPORT_PREFETCH",
                "generated_at": "2026-09-18T04:20:00+07:00",
                "source_run_id": "core-run-77",
                "report_prefetch_run_id": "prefetch-run-88",
            },
            {
                "scope": "PERSONAL",
                "generated_at": "2026-09-18T04:21:00+07:00",
                "source_run_id": "core-run-77",
                "report_prefetch_run_id": "prefetch-run-OLD",
            },
        ],
        logical_slot="2026-09-18T04:30:00+07:00",
        observed_at="2026-09-18T04:30:00+07:00",
        maximum_age_minutes=35,
    )

    assert lineage["generation_coherent"] is False
    assert lineage["cross_generation_mix_blocked"] is True
    assert lineage["freshness_status"] == "CROSS_GENERATION"
    assert lineage["usable"] is False
