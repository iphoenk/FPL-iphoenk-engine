from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one replacement in {relative}, found {count}: {old[:120]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


# An exact modulo partition may legitimately contain zero root prefixes.
replace_once(
    "src/services/package_optimization_shard_service.py",
    '    if diagnostics.get("incoming_prefixes_selected",0) <= 0: raise RuntimeError("empty incoming-prefix partition cell")\n',
    '',
)

# Fan-in must bind the deterministic partition scheme before deriving inner disjointness.
replace_once(
    "src/engines/v4_full_universe_package_shard_merge.py",
    '''    grouped = defaultdict(list)\n    global_total_set = set()\n    outgoing_sets = {}\n    incoming_complete = True\n''',
    '''    partition_schemes = {str(((r.get("search") or {}).get("diagnostics") or {}).get("partition_scheme") or "") for r in cells}\n    expected_scheme = "OUTGOING_JOB_ORDINAL_MODULO_X_ROOT_INCOMING_COMBO_ORDINAL_MODULO"\n    if partition_schemes != {expected_scheme}:\n        raise RuntimeError("2D shard partition scheme mismatch")\n    grouped = defaultdict(list)\n    global_total_set = set()\n    outgoing_sets = {}\n    incoming_complete = True\n    incoming_disjoint = True\n''',
)
replace_once(
    "src/engines/v4_full_universe_package_shard_merge.py",
    '''        selected = sum(int((r.get("search") or {}).get("diagnostics", {}).get("incoming_prefixes_selected") or 0) for r in rows)\n        incoming_complete = incoming_complete and selected == prefix_total\n''',
    '''        selected_by_index = {\n            int((r.get("search") or {}).get("incoming_prefix_shard_index")): int((r.get("search") or {}).get("diagnostics", {}).get("incoming_prefixes_selected") or 0)\n            for r in rows\n        }\n        incoming_disjoint = incoming_disjoint and set(selected_by_index) == set(range(ic))\n        selected = sum(selected_by_index.values())\n        incoming_complete = incoming_complete and selected == prefix_total\n''',
)
replace_once(
    "src/engines/v4_full_universe_package_shard_merge.py",
    '''    if not outgoing_complete or not incoming_complete:\n        raise RuntimeError("2D partition coverage proof failed")\n''',
    '''    if not outgoing_complete or not incoming_complete or not incoming_disjoint:\n        raise RuntimeError("2D partition coverage proof failed")\n''',
)
replace_once(
    "src/engines/v4_full_universe_package_shard_merge.py",
    '''        "incoming_prefix_partitions_complete": incoming_complete,\n        "shard_partitions_disjoint": outgoing_disjoint, "shard_partitions_complete": outgoing_complete and incoming_complete,\n''',
    '''        "incoming_prefix_partitions_disjoint": incoming_disjoint,\n        "incoming_prefix_partitions_complete": incoming_complete,\n        "shard_partitions_disjoint": outgoing_disjoint and incoming_disjoint,\n        "shard_partitions_complete": outgoing_complete and incoming_complete,\n''',
)

# Bind explicit inner-disjoint proof into the manifest contract.
replace_once(
    "src/services/package_optimization_merge_service.py",
    '''"shard_partition_disjointness_proven":True,"shard_partition_completeness_proven":True,"execution_registry_authoritative":True,''',
    '''"shard_partition_disjointness_proven":True,"shard_partition_completeness_proven":True,"incoming_prefix_partition_disjointness_proven":True,"execution_registry_authoritative":True,''',
)

# Unit proof must expose both dimensions.
path = ROOT / "tests/test_v4_exact_workflow_shard_merge.py"
text = path.read_text(encoding="utf-8")
old = 'assert d["workflow_worker_count"]==4; assert d["outgoing_partitions_complete"] is True; assert d["incoming_prefix_partitions_complete"] is True; assert d["shard_partitions_complete"] is True'
new = 'assert d["workflow_worker_count"]==4; assert d["outgoing_partitions_complete"] is True; assert d["incoming_prefix_partitions_disjoint"] is True; assert d["incoming_prefix_partitions_complete"] is True; assert d["shard_partitions_disjoint"] is True; assert d["shard_partitions_complete"] is True'
if old not in text:
    raise RuntimeError("missing 2D merge proof assertion")
path.write_text(text.replace(old, new, 1), encoding="utf-8")

print("2D exact partition proof hardened; empty cells are legal")
