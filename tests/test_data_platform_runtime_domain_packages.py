from __future__ import annotations

import importlib
from pathlib import Path


EXPECTED_DOMAINS = {
    "acquisition",
    "identity",
    "publication",
    "control_plane",
    "report_plane",
    "observability",
    "governance",
}


def test_runtime_v6_domain_packages_exist_and_import():
    for domain in EXPECTED_DOMAINS:
        module = importlib.import_module(f"src.runtime_v6.{domain}")
        assert module is not None


def test_domain_layout_owns_each_migrated_module_once():
    from src.runtime_v6.domain_layout import DOMAIN_MODULE_MAP

    assert set(DOMAIN_MODULE_MAP) == EXPECTED_DOMAINS
    owned = [name for modules in DOMAIN_MODULE_MAP.values() for name in modules]
    assert len(owned) == len(set(owned))
    assert "temporal" in DOMAIN_MODULE_MAP["control_plane"]
    assert "report_delivery" in DOMAIN_MODULE_MAP["report_plane"]
    assert "identity" in DOMAIN_MODULE_MAP["identity"]
    assert "collector" in DOMAIN_MODULE_MAP["acquisition"]
    assert "publish_integrity" in DOMAIN_MODULE_MAP["publication"]
    assert "report_observability" in DOMAIN_MODULE_MAP["observability"]
    assert "authority_contract" in DOMAIN_MODULE_MAP["governance"]


def test_domain_modules_must_not_import_their_flat_facades():
    from src.runtime_v6.domain_layout import DOMAIN_MODULE_MAP

    root = Path("src/runtime_v6")
    for domain, modules in DOMAIN_MODULE_MAP.items():
        for module_name in modules:
            path = root / domain / f"{module_name}.py"
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            forbidden_absolute = f"from src.runtime_v6.{module_name} import"
            forbidden_relative = f"from ..{module_name} import"
            assert forbidden_absolute not in text, str(path)
            assert forbidden_relative not in text, str(path)


def test_flat_compatibility_facades_are_bounded_after_migration():
    from src.runtime_v6.domain_layout import DOMAIN_MODULE_MAP

    root = Path("src/runtime_v6")
    for domain, modules in DOMAIN_MODULE_MAP.items():
        for module_name in modules:
            canonical = root / domain / f"{module_name}.py"
            facade = root / f"{module_name}.py"
            if not canonical.exists() or not facade.exists():
                continue
            text = facade.read_text(encoding="utf-8")
            assert len(text.splitlines()) <= 24, str(facade)
            assert f"runtime_v6.{domain}.{module_name}" in text or f".{domain}.{module_name}" in text, str(facade)
