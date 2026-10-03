from src.engines.v12_material_news import (
    build_official_fpl_material_news,
    build_report_time_material_news,
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


def test_official_news_older_than_previous_deep_is_not_repeated():
    rows = build_official_fpl_material_news(
        {
            "elements": [
                {
                    "id": 7,
                    "web_name": "Player Seven",
                    "team": 3,
                    "news": "Old availability note",
                    "news_added": "2026-10-03T03:00:00+00:00",
                }
            ]
        },
        our_element_ids=[7],
        watchlist_element_ids=[],
        report_timestamp="2026-10-03T12:30:00+07:00",
        previous_report_timestamp="2026-10-03T11:00:00+07:00",
    )
    assert rows == []


def test_external_rumor_contract_never_self_authorizes_action():
    row = normalize_material_news_item(
        {
            "subject": "Player",
            "summary": "Circulating possible benching",
            "source_class": "RUMOR / UNVERIFIED",
            "source_name": "Unverified circulation",
            "decision_relevance": "MONITOR",
        }
    )
    assert row["source_class"] == "RUMOR / UNVERIFIED"
    assert row["evidence_status"] == "UNVERIFIED"
    assert row["act_authority"] is False
    assert row["news_observation_is_model_update"] is False


def test_report_time_evidence_surfaces_official_report_and_rumor_labels():
    bootstrap = {
        "teams": [{"id": 3, "name": "Example FC"}],
        "elements": [
            {
                "id": 7,
                "web_name": "Player Seven",
                "first_name": "Player",
                "second_name": "Seven",
                "team": 3,
            },
            {
                "id": 8,
                "web_name": "Player Eight",
                "first_name": "Player",
                "second_name": "Eight",
                "team": 3,
            },
        ],
    }
    evidence = {
        "contract": "report_time_evidence_v1",
        "signals": [
            {
                "source_id": "premier_league_official_news",
                "source_class": "VERIFIED_NEWS",
                "topic": "AVAILABILITY",
                "subject": "Player Seven",
                "stance": "HOLD",
                "observed_at": "2026-10-03T04:00:00Z",
                "source_url": "https://www.premierleague.com/example",
                "summary": "Manager says Player Seven trained normally.",
            },
            {
                "source_id": "rotowire",
                "source_class": "SECONDARY_AVAILABILITY",
                "topic": "PREDICTED_LINEUP",
                "subject": "Player Eight",
                "stance": "START",
                "observed_at": "2026-10-03T04:10:00Z",
                "source_url": "https://www.rotowire.com/example",
                "summary": "Player Eight is projected to start.",
            },
            {
                "source_id": "reddit_fantasypl",
                "source_class": "COMMUNITY_SIGNAL",
                "topic": "ROTATION_OBSERVATION",
                "subject": "Player Seven",
                "stance": "BENCH",
                "observed_at": "2026-10-03T04:20:00Z",
                "source_url": "https://www.reddit.com/r/FantasyPL/example",
                "summary": "Possible benching is circulating.",
            },
            {
                "source_id": "premier_league_official_news",
                "source_class": "VERIFIED_NEWS",
                "topic": "AVAILABILITY",
                "subject": "Unrelated Player",
                "stance": "HOLD",
                "observed_at": "2026-10-03T04:00:00Z",
                "source_url": "https://www.premierleague.com/unrelated",
                "summary": "Unrelated news.",
            },
        ],
    }
    rows = build_report_time_material_news(
        evidence,
        bootstrap,
        our_element_ids=[7],
        watchlist_element_ids=[8],
        report_timestamp="2026-10-03T12:30:00+07:00",
    )
    assert len(rows) == 3
    official = next(row for row in rows if row["source_name"] == "premier_league_official_news")
    reliable = next(row for row in rows if row["source_name"] == "rotowire")
    rumor = next(row for row in rows if row["source_name"] == "reddit_fantasypl")
    assert official["source_class"] == "OFFICIAL"
    assert official["audience"] == "OUR15"
    assert reliable["source_class"] == "RELIABLE_REPORT"
    assert reliable["audience"] == "WATCHLIST / TARGETS"
    assert rumor["source_class"] == "RUMOR / UNVERIFIED"
    assert rumor["evidence_status"] == "UNVERIFIED"
    assert rumor["act_authority"] is False
    assert all(row["subject"] != "Unrelated Player" for row in rows)
