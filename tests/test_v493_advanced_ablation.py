from src.engines.v4_advanced_ablation import compare_decisions, compare_predictions, parity_report


def _pred(rows):
    return {
        "players": [
            {
                "element": element,
                "name": name,
                "position": "MID",
                "xpts_3": x5 * 0.6,
                "xpts_5": x5,
                "xpts_10": x5 * 2,
                "xpts_15": x5 * 3,
                "uncertainty": 1.0,
            }
            for element, name, x5 in rows
        ]
    }


def test_full_shadow_parity_requires_same_numeric_prediction_graph():
    full = _pred([(1, "A", 5.0), (2, "B", 4.0)])
    same = _pred([(1, "A", 5.0), (2, "B", 4.0)])
    changed = _pred([(1, "A", 5.2), (2, "B", 4.0)])
    assert parity_report(full, same)["ok"] is True
    report = parity_report(full, changed)
    assert report["ok"] is False
    assert report["mismatches"]


def test_prediction_ablation_reports_xpts_and_rank_displacement():
    full = _pred([(1, "A", 6.0), (2, "B", 5.0), (3, "C", 4.0)])
    noadv = _pred([(1, "A", 4.5), (2, "B", 5.2), (3, "C", 4.0)])
    report = compare_predictions(full, noadv)
    assert report["players"] == 3
    assert report["max_abs_delta_xpts5"] == 1.5
    assert report["max_abs_rank_shift"] >= 1
    assert report["players_abs_delta_ge"]["0.50"] == 1
    assert report["largest_impacts"][0]["element"] == 1


def test_decision_ablation_detects_classification_and_squad_change():
    full = {
        "classification": "MATERIAL_UPGRADE",
        "optimized_elements": list(range(1, 16)),
        "out": [{"element": 1}],
        "in": [{"element": 16}],
        "delta": {"best_xi_xpts_5": 5.0, "bench_adjusted_utility_5": 5.5},
    }
    noadv = {
        "classification": "KEEP_15",
        "optimized_elements": list(range(2, 17)),
        "out": [],
        "in": [],
        "delta": {"best_xi_xpts_5": 0.5, "bench_adjusted_utility_5": 0.7},
    }
    report = compare_decisions(full, noadv)
    assert report["classification_changed"] is True
    assert report["optimized_squad_changed_players"] == 2
    assert report["decision_changed"] is True
