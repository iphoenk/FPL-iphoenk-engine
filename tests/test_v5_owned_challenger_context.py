from src.v5.evaluation.owned_challenger_context import enrich_with_decision_context


def _pair(*, lane="GOVERNED_WATCHLIST", classification="WATCH_CHALLENGER", signal="INTERESTING"):
    return {
        "owned": {"element": 1, "name": "Owned"},
        "challenger": {"element": 101, "name": "Challenger", "lane": lane},
        "horizons": {"5": {"raw_gain": 2.5}},
        "performance_signal": signal,
        "classification": classification,
        "reasons": [],
        "evidence": {},
    }


def test_exact_canonical_single_package_supplies_legality_and_net_transfer_value():
    comparator = {"pairs": [_pair()], "top_comparisons": [_pair()]}
    decision = {
        "local_legality_prevalidated": True,
        "hold": {"id": "HOLD", "score": {"robust_score": 40.0}},
        "packages": [
            {
                "id": "1:1->101",
                "changes": 1,
                "outs": [{"element": 1}],
                "ins": [{"element": 101}],
                "legal": True,
                "affordability": {"resulting_itb": 2},
                "score": {"robust_score": 43.25},
            }
        ],
    }
    out = enrich_with_decision_context(comparator, decision)
    row = out["pairs"][0]
    assert row["canonical_package_context"]["status"] == "VERIFIED"
    assert row["canonical_package_context"]["legal"] is True
    assert row["canonical_package_context"]["net_transfer_value"] == 3.25
    assert row["transfer_economics"]["net_transfer_value"] == 3.25
    assert row["evidence"]["canonical_legality"] == "VERIFIED"


def test_missing_exact_package_is_unverified_not_illegal():
    comparator = {"pairs": [_pair()], "top_comparisons": [_pair()]}
    decision = {"local_legality_prevalidated": True, "packages": []}
    row = enrich_with_decision_context(comparator, decision)["pairs"][0]
    assert row["canonical_package_context"]["status"] == "UNVERIFIED"
    assert row["canonical_package_context"]["legal"] is None
    assert row["evidence"]["canonical_legality"] == "UNVERIFIED"
    assert row["transfer_economics"]["opportunity_cost"] == "PENDING"


def test_emerging_watch_grade_signal_promotes_to_watchlist_advisory_only():
    comparator = {"pairs": [_pair(lane="EMERGING_CHALLENGER")], "top_comparisons": []}
    row = enrich_with_decision_context(comparator, {})["pairs"][0]
    assert row["classification"] == "PROMOTE_TO_WATCHLIST"
    assert row["watchlist_mutation"] is False
    assert "EMERGING_CHALLENGER_EARNS_ADVISORY_WATCHLIST_PROMOTION" in row["reasons"]


def test_review_grade_emerging_signal_remains_review_not_silently_downgraded():
    comparator = {"pairs": [_pair(lane="EMERGING_CHALLENGER", classification="REVIEW", signal="STRONG")], "top_comparisons": []}
    row = enrich_with_decision_context(comparator, {})["pairs"][0]
    assert row["classification"] == "REVIEW"
    assert row["watchlist_mutation"] is False
