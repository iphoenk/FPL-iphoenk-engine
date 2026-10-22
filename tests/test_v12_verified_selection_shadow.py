from __future__ import annotations

from copy import deepcopy

import pytest

from src.engines.v12_verified_selection_shadow import evaluate_official_selection_shadow

SHA = "a" * 64
CUTOFF = "2026-10-22T04:00:00Z"
DEADLINE = "2026-10-24T12:00:00Z"
RECEIPT = {
    "source_id": "official_fpl",
    "artifact_sha256": SHA,
    "original_git_readback": "PASS",
    "observed_at": "2026-10-22T03:55:00Z",
}
PLAYER = {
    "id": 101, "team": 5, "element_type": 3,
    "status": "a", "starts": 0, "minutes": 0,
}


def row(fixture, gw, started, minutes):
    return {
        "source_id": "official_fpl",
        "source_snapshot_sha256": SHA,
        "official_element_id": 101,
        "official_fixture_id": fixture,
        "gw": gw,
        "identity_status": "EXACT",
        "fixture_identity_status": "VERIFIED",
        "fixture_finished": True,
        "official_status": "FINAL" if minutes > 0 else "DNP",
        "starter": started, "minutes": minutes,
        "observed_at": "2026-10-22T03:50:00Z",
    }


STABLE = [row(11, 1, True, 90), row(21, 2, True, 78), row(31, 3, True, 86),
          row(41, 4, True, 90)]
ROTATING = [row(11, 1, True, 90), row(21, 2, False, 12), row(31, 3, False, 0),
            row(41, 4, True, 70)]


def evaluate(rows=STABLE, *, player=PLAYER, receipt=RECEIPT, **kwargs):
    return evaluate_official_selection_shadow(
        player, rows, receipt, target_gw=8, evidence_cutoff_at=CUTOFF,
        target_deadline_at=DEADLINE, **kwargs,
    )


def test_verified_official_selection_yields_canonical_shadow_distribution():
    out = evaluate()
    assert out["status"] == "READY_SHADOW"
    assert out["verified_matches"] == 4
    assert out["selection_evidence"]["starts"] == 4
    assert 0 < out["probabilities"]["p_start"] < 1
    assert out["model_owner"] == "V12_PLAYER_MINUTES"
    assert out["shadow_only"] and not out["publication_authorized"]
    assert not out["eligible_for_live_scoring"]
    assert out["calibration"] == "NOT_VERIFIED"
    assert out["source"]["original_git_readback_reverified_locally"] is False
    probs = out["probabilities"]
    assert sum(probs.values()) == pytest.approx(1, abs=0.0003)
    assert 0 <= out["minutes"]["expected"] <= 90


def test_genuine_match_selection_changes_probability_without_new_model():
    stable = evaluate(STABLE)
    rotated = evaluate(ROTATING)
    assert stable["status"] == rotated["status"] == "READY_SHADOW"
    assert stable["probabilities"]["p_start"] > rotated["probabilities"]["p_start"]
    assert rotated["selection_evidence"]["dnp"] == 1


def test_missing_or_unverified_source_receipt_never_emits_probabilities():
    for edit in [
        {"source_id": "media"},
        {"original_git_readback": "UNVERIFIED"},
        {"artifact_sha256": "nope"},
        {"observed_at": "2026-10-25T00:00:00Z"},
        {"observed_at": "2026-10-22T03:55:00"},  # naive timezone
    ]:
        out = evaluate(receipt={**RECEIPT, **edit})
        assert out["status"] == "UNVERIFIED"
        assert out["probabilities"] is None


def test_fixture_and_player_identity_fail_closed_not_fuzzy_joined():
    variants = [
        {"official_element_id": 999},
        {"official_fixture_id": None},
        {"identity_status": "CANDIDATE"},
        {"fixture_identity_status": "UNVERIFIED"},
        {"source_id": "x"},
        {"source_snapshot_sha256": "b" * 64},
        {"fixture_finished": False},
        {"official_status": "PROVISIONAL"},
        {"gw": 9},  # future information
    ]
    for mutation in variants:
        bad = {**row(51, 5, True, 90), **mutation}
        out = evaluate([*STABLE[:2], bad])
        assert out["status"] == "INSUFFICIENT_VERIFIED_EVIDENCE", mutation
        assert out["verified_matches"] == 2
        assert out["probabilities"] is None


def test_untrusted_starter_encodings_and_minute_contradictions_do_not_turn_into_true():
    variants = [
        {"starter": "false"},
        {"starter": 1},
        {"starter": False, "minutes": -5},
        {"starter": False, "minutes": 200},
        {"starter": True, "minutes": 0},
        {"starter": False, "minutes": float("nan")},
        {"starter": False, "minutes": True},
        {"starter": True, "minutes": 12, "official_status": "DNP"},
    ]
    for mutation in variants:
        bad = {**row(51, 5, False, 0), **mutation}
        out = evaluate([*STABLE[:2], bad])
        assert out["status"] == "INSUFFICIENT_VERIFIED_EVIDENCE", mutation
        assert out["probabilities"] is None


def test_conflicting_fixture_observations_quarantine_both_not_pick_higher_minutes():
    a = row(71, 7, True, 85)
    b = row(71, 7, False, 7)
    out = evaluate([*STABLE[:2], a, b])
    assert out["status"] == "INSUFFICIENT_VERIFIED_EVIDENCE"
    assert out["verified_matches"] == 2
    assert out["rejected"]["CONFLICTED_FIXTURE"] == 1


def test_republication_of_identical_row_does_not_inflate_selection_count():
    base = evaluate(STABLE)
    duplicate = evaluate([*STABLE, deepcopy(STABLE[0]), deepcopy(STABLE[0])])
    assert base["probabilities"] == duplicate["probabilities"]
    assert duplicate["verified_matches"] == len(STABLE)
    assert duplicate["rejected"]["DUPLICATE_SAME_OBSERVATION"] == 2


def test_asof_source_timestamp_and_predeadline_requirements():
    later_row = {**row(51, 5, True, 70), "observed_at": "2026-10-22T04:05:00Z"}
    out = evaluate([*STABLE[:2], later_row])
    assert out["status"] == "INSUFFICIENT_VERIFIED_EVIDENCE"
    assert out["rejected"]["ROW_NOT_OBSERVED_PREDEADLINE"] == 1
    no_capture = evaluate_official_selection_shadow(
        PLAYER, STABLE, RECEIPT, target_gw=8,
        evidence_cutoff_at="2026-10-24T12:00:00Z", target_deadline_at=DEADLINE,
    )
    assert no_capture["status"] == "UNVERIFIED"


def test_low_sample_has_no_probability_rather_than_fabricated_precision():
    out = evaluate(STABLE[:2])
    assert out["status"] == "INSUFFICIENT_VERIFIED_EVIDENCE"
    assert out["probabilities"] is None
    assert out["minutes"] is None


def test_result_is_deterministic_and_does_not_mutate_inputs():
    player, rows, receipt = deepcopy(PLAYER), deepcopy(STABLE), deepcopy(RECEIPT)
    first = evaluate(rows, player=player, receipt=receipt)
    second = evaluate(rows, player=player, receipt=receipt)
    assert first == second
    assert player == PLAYER and rows == STABLE and receipt == RECEIPT


def test_no_opinion_media_news_or_fpl_25_50_75_flags_as_probability():
    for flag in [25, 50, 75]:
        out = evaluate(player={**PLAYER, "chance_of_playing_next_round": flag})
        base = evaluate()
        assert out["probabilities"]["p_start"] == base["probabilities"]["p_start"]


def test_no_unverified_probabilities_are_published():
    source = __import__("inspect").getsource(evaluate_official_selection_shadow)
    assert "publicDecision" not in source
    assert "model_owner" in source or "estimate_player_minutes" in source
    for status in [evaluate(), evaluate(STABLE[:2]), evaluate(receipt={})]:
        assert status["publication_authorized"] is False
        assert status["eligible_for_live_scoring"] is False
