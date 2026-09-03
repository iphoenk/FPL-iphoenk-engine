from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one replacement in {relative}, found {count}: {old[:140]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


# The fan-in semantic fingerprint is intentionally strict. Test cells must share the
# same roll baseline exactly, just like real shards from one immutable input snapshot.
replace_once(
    "tests/test_v4_exact_workflow_shard_merge.py",
    '    roll=dict(pkg,package_id="ROLL_BASELINE",replacements=0,adjusted_utility_gain_5=0.0,classification="ROLL_BASELINE")\n',
    '    roll=dict(pkg,package_id="ROLL_BASELINE",replacements=0,adjusted_utility_gain_5=0.0,adjusted_best_xi_gain_5=0.0,net_xpts_3=0.0,net_xpts_5=0.0,net_xpts_10=0.0,net_xpts_15=0.0,classification="ROLL_BASELINE")\n',
)

# The proof fixture must declare the same deterministic partition scheme as runtime.
replace_once(
    "tests/test_v4_exact_workflow_shard_merge.py",
    '"incoming_prefixes_total":ic,"incoming_prefixes_selected":1,"packages_evaluated":1}',
    '"incoming_prefixes_total":ic,"incoming_prefixes_selected":1,"packages_evaluated":1,"partition_scheme":"OUTGOING_JOB_ORDINAL_MODULO_X_ROOT_INCOMING_COMBO_ORDINAL_MODULO"}',
)

print("2D exact merge fixture aligned to strict semantic fingerprint and partition contract")
