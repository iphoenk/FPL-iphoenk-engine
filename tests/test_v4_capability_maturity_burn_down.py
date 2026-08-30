from __future__ import annotations

import json
from datetime import datetime, timezone

from src.engines import v4_maturity_reconciler as maturity
from src.engines.v4_maturity_reconciler import (
    _ownership_evidence,
    _prior_evidence,
    _rotation_evidence,
    _schedule_capability_evidence,
    _set_readiness,
)
from src.engines.v4_preseason_evidence import load_verified_preseason_evidence
from src.engines.v4_runner import minutes_contexts, player_priors
from src.engines.v4_xmins_evidence import attach_xmins_evidence
from src.services.competitive_load_service import build_competitive_load


def _policy() -> dict:
    return {
        "contract": "RECENT_COMPETITIVE_LOAD_V2",
        "xmins_handoff": {"enabled": True, "direct_xpts_mutation_forbidden": True},
    }


def _snapshot() -> dict:
    return {
        "generated_at": "2026-08-30T12:00:00+00:00",
        "phase": {"scoring_gw": 2},
        "official": {
            "bootstrap": {
                "teams": [{"id": 1, "name": "Alpha"}, {"id": 2, "name": "Beta"}],
                "elements": [
                    {"id": 10, "web_name": "A", "team": 1},
                    {"id": 20, "web_name": "B", "team": 2},
                ],
            },
            "fixtures": [
                {"id": 101, "team_h": 1, "team_a": 2, "kickoff_time": "2026-08-29T12:00:00Z"},
                {"id": 201, "team_h": 2, "team_a": 1, "kickoff_time": "2026-09-01T12:00:00Z"},
            ],
            "event_live": {"elements": {}},
        },
    }


def test_failed_runtime_proof_demotes_previous_active_status() -> None:
    row = {"id": "DSS-30", "status": "ACTIVE"}
    assert _set_readiness(row, False, {"implementation_state": "PARTIAL"}) is False
    assert row["status"] == "PARTIAL"


def test_external_competitive_intake_is_verified_and_unverified_rows_are_zero_signal() -> None:
    external = {
        "player_matches": [
            {
                "element": 10,
                "competition_type": "EUROPEAN",
                "competition": "UEFA Champions League",
                "match_time": "2026-08-28T12:00:00Z",
                "minutes": 90,
                "started": True,
                "extra_time_minutes": 0,
                "source": "official competition match centre",
                "verified_at": "2026-08-29T08:00:00Z",
                "verified": True,
            },
            {
                "element": 20,
                "competition_type": "INTERNATIONAL",
                "match_time": "2026-08-28T12:00:00Z",
                "minutes": 90,
                "source": "unverified claim",
                "verified_at": "2026-08-29T08:00:00Z",
                "verified": False,
            },
        ]
    }
    load = build_competitive_load(_snapshot(), external_evidence=external)
    assert load["coverage"]["european_verified_player_fixture_rows"] == 1
    assert load["coverage"]["international_verified_player_fixture_rows"] == 0
    assert load["coverage"]["external_rejected_rows"] == 1
    assert load["guardrails"]["unverified_external_competitive_signal_is_zero"] is True

    predictions = {
        "players": [{
            "element": 10,
            "fixtures": [{
                "xpts": 5.0,
                "xmins": {"start_probability": 0.8, "start_probability_confidence": 0.5},
            }],
        }]
    }
    before_xpts = predictions["players"][0]["fixtures"][0]["xpts"]
    before_start = predictions["players"][0]["fixtures"][0]["xmins"]["start_probability"]
    attach_xmins_evidence(predictions, load, now=datetime(2026, 8, 30, tzinfo=timezone.utc))
    fixture = predictions["players"][0]["fixtures"][0]
    assert fixture["xpts"] == before_xpts
    assert fixture["xmins"]["start_probability"] == before_start
    assert fixture["xmins"]["source_decomposition"]["competitive_load"]["external_evidence_state"] == "VERIFIED"
    assert predictions["capability_evidence"]["competitive_load_consumer_active"] is True


def test_schedule_readiness_requires_producer_consumer_wiring_not_current_external_rows() -> None:
    competitive = build_competitive_load(_snapshot())
    predictions = {
        "capability_evidence": {"competitive_load_consumer_active": True},
        "guardrails": {
            "competitive_load_direct_xpts_mutation_forbidden": True,
            "competitive_load_direct_start_probability_mutation_forbidden": True,
        },
    }
    ok, detail = _schedule_capability_evidence(competitive, _policy(), predictions, "DSS-30")
    assert ok is True
    assert detail["evidence_state"] == "EVIDENCE_GATED"
    broken = json.loads(json.dumps(competitive))
    broken["guardrails"]["verified_external_competitive_intake_wired"] = False
    ok, _ = _schedule_capability_evidence(broken, _policy(), predictions, "DSS-30")
    assert ok is False


def test_rotation_maturity_does_not_require_any_unadjusted_player() -> None:
    predictions = {
        "players": [
            {"priors": {
                "competition_pressure": 0.2,
                "competition_source": "inferred_tactical_role_peer_group",
                "squad_depth_pressure": 0.1,
                "competition_factor": 0.94,
                "competition_adjustment_applied": True,
            }},
            {"priors": {
                "competition_pressure": 0.5,
                "competition_source": "inferred_tactical_role_peer_group",
                "squad_depth_pressure": 0.2,
                "competition_factor": 0.86,
                "competition_adjustment_applied": True,
            }},
        ]
    }
    ok, detail = _rotation_evidence(predictions)
    assert ok is True
    assert detail["distinct_competition_factors"] == 2
    assert detail["semantic_consistency_rows"] == 2


def test_verified_preseason_role_is_joined_by_official_element_before_projection(tmp_path) -> None:
    path = tmp_path / "preseason.json"
    path.write_text(json.dumps({
        "contract": "PRESEASON_EVIDENCE_V1",
        "season": "2026-27",
        "players": [
            {
                "element": 10,
                "role": "creator_midfielder",
                "minutes": 180,
                "starts": 2,
                "source": "official club reports",
                "verified_at": "2026-08-01T00:00:00Z",
                "verified": True,
            },
            {
                "element": 20,
                "role": "striker",
                "source": "unverified",
                "verified_at": "2026-08-01T00:00:00Z",
                "verified": False,
            },
        ],
    }))
    evidence, meta = load_verified_preseason_evidence(path)
    assert set(evidence) == {10}
    assert meta["preseason_identity_join"] == "official_element_id"
    assert meta["preseason_rejected_rows"] == 1

    elements = [
        {"id": 10, "team": 1, "element_type": 3, "starts": 0, "minutes": 0, "now_cost": 70},
        {"id": 20, "team": 1, "element_type": 3, "starts": 0, "minutes": 0, "now_cost": 60},
    ]
    contexts = minutes_contexts(elements, {}, 1, preseason=evidence)
    assert contexts[10]["tactical_role"] == "creator_midfielder"
    assert contexts[10]["tactical_role_source"] == "verified_preseason_role"
    assert contexts[10]["preseason_role_consumed"] is True
    assert contexts[20]["preseason_evidence_state"] == "EVIDENCE_GATED"


def test_historical_prior_requires_actual_weighted_consumption() -> None:
    fake = {
        "input_coverage": {"last_season_matched": 1},
        "players": [{"priors": {"prior_season_available": True, "last_season_weight": 0, "last_season_source": None}}],
    }
    ok, _ = _prior_evidence(fake, "historical")
    assert ok is False
    real = {
        "input_coverage": {"last_season_matched": 1},
        "players": [{"priors": {"last_season_weight": 0.4, "last_season_source": "previous-season"}}],
    }
    ok, detail = _prior_evidence(real, "historical")
    assert ok is True
    assert detail["historical_prior_rows_consumed"] == 1


def test_official_ownership_is_material_model_prior_not_flag_only() -> None:
    low = {
        "element_type": 3,
        "now_cost": 70,
        "selected_by_percent": "1.0",
        "creativity": "20",
        "threat": "20",
    }
    high = {**low, "selected_by_percent": "35.0"}
    low_prior = player_priors(low)
    high_prior = player_priors(high)
    assert high_prior["role_prior"] > low_prior["role_prior"]
    assert high_prior["xg90_prior"] > low_prior["xg90_prior"]
    assert high_prior["xa90_prior"] > low_prior["xa90_prior"]

    latest = {"official_context": {
        "official_fpl_first": True,
        "player_field_coverage": {"ownership": 2},
    }}
    universe = {"players": [{"ownership": 1.0}, {"ownership": 35.0}]}
    predictions = {
        "players": [{}, {}],
        "capability_evidence": {
            "official_ownership_rows": 2,
            "ownership_context_consumed_players": 2,
        },
    }
    ok, detail = _ownership_evidence(latest, universe, predictions)
    assert ok is True
    assert detail["effective_ownership_state"] == "OPTIONAL_EXTERNAL_ADVISORY"


def test_calibration_warmup_requires_canonical_quality_gate(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(maturity, "RECONCILED", tmp_path)
    monkeypatch.setattr(maturity, "reconciled_integrity", lambda sample, model_version=None: (True, None))
    sample = {
        "gw": 1,
        "model_version": "v-test",
        "report": {"metrics": {
            "status": "PASS",
            "n": 299,
            "mae": 2.0,
            "ranking": {"spearman": 0.4},
            "interval80_coverage": 0.8,
        }},
    }
    path = tmp_path / "gw01.json"
    path.write_text(json.dumps(sample))

    ok, detail = maturity._calibration_maturity_evidence({"model_version": "v-test"})
    assert ok is False
    assert detail["implementation_state"] == "WARMUP"
    assert detail["minimum_n"] == 300
    assert detail["best_observed_n"] == 299

    sample["report"]["metrics"]["n"] = 300
    path.write_text(json.dumps(sample))
    ok, detail = maturity._calibration_maturity_evidence({"model_version": "v-test"})
    assert ok is True
    assert detail["implementation_state"] == "ACTIVE"
    assert detail["passing_gws"] == [1]


def test_invalid_reconciliation_cannot_promote_warmup(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(maturity, "RECONCILED", tmp_path)
    monkeypatch.setattr(maturity, "reconciled_integrity", lambda sample, model_version=None: (False, "synthetic_or_invalid"))
    (tmp_path / "gw01.json").write_text(json.dumps({
        "gw": 1,
        "report": {"metrics": {
            "status": "PASS",
            "n": 999,
            "mae": 0.1,
            "ranking": {"spearman": 0.99},
            "interval80_coverage": 0.8,
        }},
    }))
    ok, detail = maturity._calibration_maturity_evidence({"model_version": "v-test"})
    assert ok is False
    assert detail["eligible_reconciled_samples"] == 0
    assert detail["rejected_samples"] == [{"file": "gw01.json", "reason": "synthetic_or_invalid"}]