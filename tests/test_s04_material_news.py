from src.engines.v12_material_news import (
    build_official_fpl_material_news,
    normalize_material_news_item,
)


def test_official_fpl_news_is_confirmed_but_not_model_update():
    rows = build_official_fpl_material_news(
        {
            "elements": [
                {
                    "id": 7,
                    "web_name": "Player Seven",
                    "team": 3,
                    "news": "Knock - 75% chance of playing",
                    "news_added": "2026-10-03T05:00:00Z",
                }
            ]
        },
        our_element_ids=[7],
        watchlist_element_ids=[],
        report_timestamp="2026-10-03T12:30:00+07:00",
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["source_class"] == "OFFICIAL"
    assert row["audience"] == "OUR15"
    assert row["evidence_status"] == "CONFIRMED_OFFICIAL_FPL_FEED"
    assert row["news_observation_is_model_update"] is False
    assert row["act_authority"] is False


def test_reliable_report_retains_label_without_becoming_model_update():
    row = normalize_material_news_item(
        {
            "subject": "Player",
            "summary": "Trained normally",
            "source_class": "RELIABLE_REPORT",
            "source_name": "Reporter",
        }
    )
    assert row["source_class"] == "RELIABLE_REPORT"
    assert row["news_observation_is_model_update"] is False
    assert row["act_authority"] is False


def test_rumor_is_always_unverified_and_cannot_authorize_act():
    row = normalize_material_news_item(
        {
            "subject": "Player",
            "summary": "Possible benching circulating",
            "source_class": "RUMOR",
            "evidence_status": "CONFIRMED",
            "decision_relevance": "MONITOR",
        }
    )
    assert row["source_class"] == "RUMOR / UNVERIFIED"
    assert row["evidence_status"] == "UNVERIFIED"
    assert row["act_authority"] is False
    assert row["news_observation_is_model_update"] is False


def test_non_owned_non_watchlist_official_news_is_not_noise_dumped():
    rows = build_official_fpl_material_news(
        {"elements": [{"id": 99, "web_name": "Noise", "news": "Minor issue"}]},
        our_element_ids=[1],
        watchlist_element_ids=[2],
        report_timestamp="2026-10-03T12:30:00+07:00",
    )
    assert rows == []
