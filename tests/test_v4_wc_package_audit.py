from src.engines.v4_wc_package_audit import _package_class


def test_package_class_tightens_with_more_changes():
    # Arguments are now delta_best_xi_xpts_5 and delta_bench_adjusted_utility_5.
    assert _package_class(2.2, 2.0, 1) == "MATERIAL_UPGRADE"
    assert _package_class(2.2, 2.0, 2) != "MATERIAL_UPGRADE"


def test_package_class_keep_small_signal():
    assert _package_class(0.4, 0.05, 1) == "KEEP_BASELINE"
