from __future__ import annotations

from src.runtime_v6.source_native import build_source_native_datasets


HTML = """
<div class="lineup is-soccer" data-gameid="123">
  <div class="lineup__time">September 13 11:00 AM</div>
  <div class="lineup__mteam is-home"><a title="Alpha"><div class="lineup__abbr">ALP</div>Alpha</a></div>
  <div class="lineup__mteam is-visit"><a title="Beta"><div class="lineup__abbr">BET</div>Beta</a></div>
  <ul class="lineup__list is-home">
    <li class="lineup__status is-expected">Predicted Lineup</li>
    <li class="lineup__player"><div class="lineup__pos">M</div><a title="Player One" href="/soccer/player/player-one-101">One</a></li>
  </ul>
</div>
"""


def test_rotowire_source_native_dataset_is_advisory_and_never_v6_authored_prediction():
    results = {
        "rotowire": {
            "source_id": "rotowire",
            "checked_at": "2026-09-06T22:00:00+00:00",
            "health": "GREEN",
            "effective_state": "LIVE_CHANGED",
            "current_run_action": "FETCHED",
            "data": {
                "lineups": {
                    "body": HTML,
                    "sha256": "abc123",
                }
            },
        }
    }

    dataset = build_source_native_datasets(results, identity_map={})["rotowire"]

    assert dataset["normalization_status"] == "NORMALIZED"
    assert dataset["record_count"] >= 2
    assert dataset["semantic_class"] == "UPSTREAM_MODEL_SIGNAL"
    assert dataset["model_author"] == "ROTOWIRE"
    assert dataset["v6_computation"] == "NONE"
    assert dataset["authority_ceiling"] == "ADVISORY"
    assert dataset["governance"]["decision_authority"] == "NONE"
    assert dataset["governance"]["prediction_authority"] == "NONE"
    assert dataset["governance"]["requires_primary_crosscheck_for_fact_promotion"] is True
    assert dataset["governance"]["may_override_verified_facts"] is False
    player = dataset["record_groups"]["lineups"][0]
    assert player["source_native_id"] == 101
    assert player["official_element_id"] is None
    assert player["identity_status"] == "UNMAPPED"
