from src.engines.v4_wc_package_audit import _package_class


def test_package_class_tightens_with_more_changes():
    assert _package_class(2.2, 0.30, 1) == "MATERIAL_UPGRADE"
    assert _package_class(2.2, 0.30, 2) != "MATERIAL_UPGRADE"


def test_package_class_keep_small_signal():
    assert _package_class(0.4, 0.05, 1) == "KEEP_BASELINE"
