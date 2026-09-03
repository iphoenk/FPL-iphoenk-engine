from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "tests/test_v4_p1_structural_hardening.py"
text = path.read_text(encoding="utf-8")
old = '    package_service_source = _text("src/services/package_optimization_service.py")\n'
new = old + '    package_shard_source = _text("src/services/package_optimization_shard_service.py")\n'
if text.count(old) != 1:
    raise RuntimeError("expected package service source declaration once")
text = text.replace(old, new)
replacements = {
    '    assert "from src.engines.v4_full_universe_package_search import search_full_universe_packages" in package_service_source\n':
        '    assert "search_full_universe_packages(" not in package_service_source\n    assert "validate_package_optimization_artifact()" in package_service_source\n    assert "from src.engines.v4_full_universe_package_search import search_full_universe_packages" in package_shard_source\n',
    '    assert "search_full_universe_packages(" in package_service_source\n':
        '    assert "search_full_universe_packages(" in package_shard_source\n',
}
for before, after in replacements.items():
    if before not in text:
        raise RuntimeError(f"missing structural assertion: {before.strip()}")
    text = text.replace(before, after, 1)
needle = '    assert registry["production"]["transfer_package_optimizer"] == "src.engines.v4_full_universe_package_search.search_full_universe_packages"\n'
if needle not in text:
    raise RuntimeError("missing transfer package optimizer registry assertion")
text = text.replace(needle, needle + '    assert registry["production"]["transfer_package_execution_topology"] == "WORKFLOW_MATRIX_FANOUT_FANIN"\n    assert registry["production"]["transfer_package_shard_worker"] == "src.services.package_optimization_shard_service"\n    assert registry["production"]["transfer_package_fan_in"] == "src.services.package_optimization_merge_service"\n', 1)
path.write_text(text, encoding="utf-8")

core_path = ROOT / "src/engines/v4_full_universe_package_search_core.py"
core = core_path.read_text(encoding="utf-8")
old_annotation = "    need: Counter,\n"
new_annotation = "    need: dict[str, int],\n"
if core.count(old_annotation) != 1:
    raise RuntimeError(f"expected current exact-core need annotation once, found {core.count(old_annotation)}")
core_path.write_text(core.replace(old_annotation, new_annotation, 1), encoding="utf-8")

print("structural optimizer ownership test aligned to non-authoritative shards + single fan-in")
print("2D staging anchor aligned to current exact-core signature")
