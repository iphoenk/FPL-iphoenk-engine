from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.engines.v12_model_evidence import build_model_run_binding
from src.engines.v12_player_minutes import estimate_player_minutes
from src.models.xmins_v3 import estimate_xmins as legacy_estimate_xmins

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = json.loads((ROOT / "tests" / "fixtures" / "player_minutes_golden.json").read_text(encoding="utf-8"))
SHARED = (
    "start_probability", "bench_probability", "cameo_probability",
    "late_cameo_probability", "dnp_probability", "expected_minutes",
    "starter_minutes_if_start", "bench_minutes_if_used",
    "cameo_minutes_if_used", "late_cameo_minutes_if_used", "minutes_std",
)


def _new(case):
    return estimate_player_minutes(case["player"], case["context"])


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=lambda row: row["name"])
def test_frozen_golden_baseline(case):
    out = _new(case)
    for key, value in case["expected"].items():
        assert out[key] == value, (case["name"], key, out[key], value)


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=lambda row: row["name"])
def test_legacy_oracle_shared_numerics_are_exact(case):
    old = legacy_estimate_xmins(case["player"], case["context"])
    new = _new(case)
    for key in SHARED:
        assert new[key] == old[key], (case["name"], key, new[key], old[key])
    assert new["conditional_probabilities"] == old["conditional_probabilities"]
    assert new["start_probability_interval"] == old["start_probability_interval"]
    assert new["expected_minutes_interval"] == old["expected_minutes_interval"]
    assert new["small_sample_guard"] == old["small_sample_guard"]
    assert new["confidence"] == old["confidence"]
    assert new["evidence"] == old["evidence"]
    assert new["historical_prior"] == old["historical_prior"]
    old_states = [{k: row[k] for k in ("state","probability","minutes_mean","minutes_std")} for row in old["xmins_distribution"]["states"]]
    new_states = [{k: row[k] for k in ("state","probability","minutes_mean","minutes_std")} for row in new["xmins_distribution"]["states"]]
    assert new_states == old_states


def test_hierarchy_bench_overlap_and_appearance_partition():
    case = next(row for row in GOLDEN["cases"] if row["name"] == "uncertain_starter")
    out = _new(case)
    c, d = out["conditional_probabilities"], out["derived_probabilities"]
    assert all(0 <= value <= 1 for value in [*c.values(), *d.values()])
    assert d["p_start"] == pytest.approx(c["p_available"] * c["p_start_given_available"], abs=1e-4)
    assert d["p_cameo"] == pytest.approx(d["p_bench"] * c["p_cameo_given_bench"], abs=1e-4)
    assert d["p_late_cameo"] == pytest.approx(d["p_cameo"] * c["p_late_cameo_given_cameo"], abs=1e-4)
    assert d["p_regular_cameo"] + d["p_late_cameo"] == pytest.approx(d["p_cameo"], abs=2e-4)
    assert d["p_start"] + d["p_regular_cameo"] + d["p_late_cameo"] + d["p_dnp"] == pytest.approx(1.0, abs=2e-4)
    assert d["p_start"] + d["p_bench"] + d["p_cameo"] + d["p_dnp"] > 1.0
    assert out["bench_is_overlapping_state"] is True


def test_availability_reduction_and_unavailable_player():
    player = {"starts":5,"minutes":420,"status":"a","chance_of_playing_next_round":100}
    context = {"team_matches_played":6,"prior_start_probability":0.85,"prior_evidence_minutes":1800}
    healthy = estimate_player_minutes(player, context)
    half = estimate_player_minutes({**player, "chance_of_playing_next_round":50}, context)
    zero = estimate_player_minutes({**player, "chance_of_playing_next_round":0}, context)
    assert half["conditional_probabilities"]["p_start_given_available"] == healthy["conditional_probabilities"]["p_start_given_available"]
    assert half["start_probability"] == pytest.approx(healthy["start_probability"] * 0.5, abs=1e-4)
    assert zero["start_probability"] == zero["bench_probability"] == zero["cameo_probability"] == 0.0
    assert zero["dnp_probability"] == 1.0


def test_dnp_absorbs_unavailable_unused_bench_and_not_selected():
    out = estimate_player_minutes(
        {"starts":2,"minutes":150,"status":"d","chance_of_playing_next_round":75},
        {"team_matches_played":5,"prior_start_probability":0.55,"prior_evidence_minutes":700},
    )
    c = out["conditional_probabilities"]
    available_not_start = c["p_available"] * (1 - c["p_start_given_available"])
    bench = available_not_start * c["p_bench_given_available_not_start"]
    expected = (1-c["p_available"]) + bench*c["p_no_appearance_given_bench"] + available_not_start*(1-c["p_bench_given_available_not_start"])
    assert out["dnp_probability"] == pytest.approx(expected, abs=2e-4)


def test_state_mixture_recomputes_mean_and_variance():
    case = next(row for row in GOLDEN["cases"] if row["name"] == "rotation_risk")
    out = _new(case)
    states = out["xmins_distribution"]["states"]
    mean = sum(row["probability"]*row["minutes_mean"] for row in states)
    second = sum(row["probability"]*(row["minutes_std"]**2 + row["minutes_mean"]**2) for row in states)
    variance = max(0.0, second - mean*mean)
    assert out["xmins_distribution"]["mean"] == pytest.approx(mean, abs=0.001)
    assert out["xmins_distribution"]["mixture_only_variance"] == pytest.approx(variance, abs=0.05)
    assert out["xmins_distribution"]["variance"] >= out["xmins_distribution"]["mixture_only_variance"]


def test_small_sample_and_missing_evidence_are_explicit():
    low = next(row for row in GOLDEN["cases"] if row["name"] == "early_season_low_sample")
    missing = next(row for row in GOLDEN["cases"] if row["name"] == "missing_historical_prior")
    low_out, missing_out = _new(low), _new(missing)
    assert low_out["small_sample_guard"] is True
    assert low_out["start_probability_interval"][1] - low_out["start_probability_interval"][0] >= 0.24
    assert missing_out["historical_prior"]["available"] is False
    assert missing_out["historical_prior"]["start_probability"] is None
    assert missing_out["evidence_lineage"]["role_start_probability"]["available"] is False
    assert missing_out["evidence_lineage"]["manager_start_probability"]["available"] is False


def test_role_present_manager_missing_is_not_fabricated():
    case = next(row for row in GOLDEN["cases"] if row["name"] == "manager_evidence_unavailable")
    out = _new(case)
    assert out["evidence_lineage"]["role_start_probability"]["available"] is True
    assert out["evidence_lineage"]["manager_start_probability"]["available"] is False


def test_identical_input_is_deterministic():
    player={"starts":4,"minutes":330,"status":"a","chance_of_playing_next_round":100}
    context={"team_matches_played":5,"prior_start_probability":0.81,"prior_evidence_minutes":1200}
    assert estimate_player_minutes(player,context) == estimate_player_minutes(player,context)


def _binding(snapshot="snap-a", model="minutes-1", calibration="cal-1"):
    return {
        **build_model_run_binding(
            input_snapshot_id=snapshot,
            factual_snapshot_timestamps={"official_fpl":"2026-09-19T12:00:00Z"},
            factual_artifact_fingerprints={"official_fpl":"a"*64},
            deterministic_factual_inputs={"ref":"runtime-data-v6/official_fpl"},
            model_version=model,
            feature_version="features-1",
            parameter_version="player-minutes-config-1",
            parameters={"config":"player_minutes.json"},
            calibration_version=calibration,
            calibration_cutoff="2026-09-19T11:00:00Z",
            calibration_parameters={"mode":"diagnostic_only"},
            generated_at="2026-09-19T12:15:00Z",
            planning_gw=5,
            canonical_v12_revision="c"*64,
        ),
        "authority":False,
        "evidence_only":True,
    }


def test_phase0_binding_changes_correct_fingerprints_without_raw_v6_duplication():
    player={"starts":4,"minutes":330,"status":"a","chance_of_playing_next_round":100}
    context={"team_matches_played":5}
    a=estimate_player_minutes(player,context,model_evidence_binding=_binding())
    b=estimate_player_minutes(player,context,model_evidence_binding=_binding(snapshot="snap-b"))
    c=estimate_player_minutes(player,context,model_evidence_binding=_binding(model="minutes-2"))
    d=estimate_player_minutes(player,context,model_evidence_binding=_binding(calibration="cal-2"))
    assert a["model_evidence"]["authority"] is False
    assert a["model_evidence"]["raw_v6_payload_persisted"] is False
    assert a["model_evidence"]["output_fingerprint"]
    assert len({a["model_evidence"]["run_fingerprint"],b["model_evidence"]["run_fingerprint"],c["model_evidence"]["run_fingerprint"],d["model_evidence"]["run_fingerprint"]}) == 4


def test_calibration_hook_is_diagnostic_only():
    out=estimate_player_minutes(
        {"starts":3,"minutes":250,"status":"a","chance_of_playing_next_round":100},
        {"team_matches_played":4},
        calibration_summary={"prediction_sample_size":12,"overall":{"starter_brier":0.18,"dnp_brier":0.11,"xmins_mae":8.2}},
    )
    hook=out["calibration_hook"]
    assert hook["calibration_confidence"] == "LOW"
    assert hook["parameters_mutated"] is False
    assert hook["automatic_retuning"] is False
    assert hook["conservative_parameters_retained"] is True


def test_production_owner_has_no_v6_runtime_v3_or_legacy_dependency():
    source=(ROOT/"src"/"engines"/"v12_player_minutes.py").read_text(encoding="utf-8")
    assert "src.runtime_v6" not in source
    assert "runtime_v3" not in source
    assert "src.models.xmins_v2" not in source
    assert "src.models.xmins_v3" not in source


def test_no_production_source_imports_xmins_v3_after_switch():
    offenders=[]
    for path in (ROOT/"src").rglob("*.py"):
        if path.name == "xmins_v3.py":
            continue
        if "src.models.xmins_v3" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_historical_projection_is_switched_to_v12_native_owner():
    source=(ROOT/"src"/"models"/"historical_projection.py").read_text(encoding="utf-8")
    assert "from src.engines.v12_player_minutes import estimate_xmins" in source
    assert "src.models.xmins_v3" not in source
