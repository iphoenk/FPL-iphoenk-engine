import pytest

from src.engines import v4_wc_optimizer, v4_wc_package_audit
from src.models import calibration as calibration_compat
from src.models import optimizer as optimizer_compat
from src.models import projection as projection_compat
from src.models import v4_calibration, v4_metrics, v4_prediction
from src.models.model_registry import register
from src.services.architecture_guard_service import run as architecture_guard_run


def test_validation_metric_compatibility_names_reuse_canonical_owner():
    assert calibration_compat.mae is v4_metrics.mae_values
    assert calibration_compat.brier is v4_metrics.brier_values
    assert calibration_compat.spearman_rank is v4_metrics.spearman_values
    assert v4_calibration.mae is v4_metrics.mae_rows
    assert v4_calibration.spearman is v4_metrics.spearman_rows
    assert v4_calibration.calibration_error is v4_metrics.calibration_error_rows


def test_canonical_metrics_preserve_existing_v4_numeric_semantics():
    actual = [1.0, 4.0, 2.0, 8.0]
    predicted = [2.0, 3.0, 2.5, 7.0]
    assert v4_metrics.mae_values(predicted, actual) == pytest.approx(0.875)
    assert v4_metrics.brier_values([0.8, 0.2], [1.0, 0.0]) == pytest.approx(0.04)
    assert v4_metrics.spearman_values(actual, predicted) == pytest.approx(1.0)
    model = register("x", "1", ["f"], "2026-08-01", actual=actual, pred=predicted)
    assert model["metrics"]["mae"] == 0.875
    assert model["metrics"]["spearman"] == 1.0


def test_legacy_projection_routes_to_canonical_v4_prediction():
    player = {
        "id": 1,
        "element_type": 3,
        "status": "a",
        "minutes": 180,
        "starts": 2,
        "expected_goals": 0.5,
        "expected_assists": 0.3,
        "bps": 20,
    }
    advanced = {"xg_per90": 0.25, "xa_per90": 0.15}
    compat = projection_compat.project_points(player, advanced, fixture_difficulty=3.0)
    canonical = v4_prediction.project_fixture(
        player,
        {"event": None, "difficulty": 3.0, "home": True},
        ctx=projection_compat._compat_context(player, advanced),
        advanced=advanced,
    )
    assert compat["projected_points"] == canonical["xpts"]
    assert compat["components"] == canonical["components"]
    assert compat["model"] == "v4_compat_adapter_to_canonical_prediction"


def test_generic_optimizer_has_no_independent_decision_authority():
    with pytest.raises(RuntimeError, match="non-authoritative"):
        optimizer_compat.score_squad([])
    with pytest.raises(RuntimeError, match="non-authoritative"):
        optimizer_compat.evaluate_package([], [], [], 1000)


def test_base_wc_optimizer_delegates_to_exact_fast_owner(monkeypatch):
    import src.engines.v4_wc_optimizer_fast as owner

    marker = {"owner": "fast"}
    monkeypatch.setattr(owner, "optimize_squad_fast", lambda *args, **kwargs: marker)
    assert v4_wc_optimizer.optimize_squad([]) is marker

    report_marker = {"report": "fast"}
    monkeypatch.setattr(owner, "decision_report_from_candidates_fast", lambda *args, **kwargs: report_marker)
    assert v4_wc_optimizer.decision_report_from_candidates([], {}) is report_marker


def test_base_package_audit_delegates_to_exact_fast_owner(monkeypatch):
    import src.engines.v4_wc_package_audit_fast as owner

    marker = {"owner": "fast-package-audit"}
    monkeypatch.setattr(owner, "audit_packages_from_candidates_fast", lambda *args, **kwargs: marker)
    assert v4_wc_package_audit.audit_packages_from_candidates([], {}) is marker


def test_architecture_guard_blocks_semantic_duplicate_business_owners():
    output = architecture_guard_run()
    assert output["status"] == "PASS"
    assert output["checks"]["generic_validation_metrics_single_owner"]["pass"] is True
    assert output["checks"]["legacy_projection_is_canonical_adapter"]["pass"] is True
    assert output["checks"]["legacy_generic_optimizer_has_no_decision_authority"]["pass"] is True
    assert output["checks"]["wc_optimizer_search_single_owner"]["pass"] is True
    assert output["checks"]["package_audit_search_single_owner"]["pass"] is True
