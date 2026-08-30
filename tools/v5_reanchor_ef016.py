from __future__ import annotations

import json
from pathlib import Path

OLD = "84b1577f4fc84ce00a4e8c5e8139644c8f9fff51"
NEW = "ef0161113a763306419c0c367770e6dcfe6570d1"


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path: str, data: dict) -> None:
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def replace_strings(value):
    if isinstance(value, str):
        return value.replace(OLD, NEW)
    if isinstance(value, list):
        return [replace_strings(item) for item in value]
    if isinstance(value, dict):
        return {key: replace_strings(item) for key, item in value.items()}
    return value


manifest_path = "config/v5_convergence_manifest.json"
manifest = replace_strings(load(manifest_path))
manifest["baselines"]["production_main_sha"] = NEW
manifest["baselines"]["production_code_commit"] = NEW
manifest["advanced_v5"]["v3_scheduler_runtime_self_heal_reconciled_as_runtime_hardening"] = True
manifest["operational_acceptance_evidence"]["validated_real_shadow_cycles"] = 0
manifest["operational_acceptance_evidence"]["remaining_validated_cycles"] = 3
manifest["operational_acceptance_evidence"]["release_fingerprint"] = None
manifest["operational_acceptance_evidence"]["operational_candidate_eligible"] = False
manifest["operational_acceptance_evidence"]["prediction_candidate_eligible"] = False
manifest["operational_acceptance_evidence"]["production_candidate_eligible"] = False
manifest["operational_acceptance_evidence"]["status"] = "SUPERSEDED_BY_PRODUCTION_REANCHOR_PENDING_REVALIDATION"
manifest["operational_acceptance_evidence"]["note"] = (
    f"Three fresh exact-fingerprint postvalidated REAL_SHADOW cycles are required against deployed production {NEW}."
)
manifest["production_promotion"]["validated_real_shadow_cycles"] = 0
manifest["production_promotion"]["operational_acceptance_complete"] = False
manifest["production_promotion"]["prediction_acceptance_complete"] = False
manifest["production_promotion"]["allowed"] = False
manifest["production_promotion"]["production_candidate"] = False
save(manifest_path, manifest)

acceptance_path = "config/v5_acceptance_registry.json"
acceptance = replace_strings(load(acceptance_path))
acceptance["convergence"]["production_main_sha"] = NEW
acceptance["convergence"]["production_code_commit"] = NEW
acceptance["convergence"]["v3_scheduler_runtime_self_heal_reconciled_as_runtime_hardening"] = True
save(acceptance_path, acceptance)

parity_path = "config/v5_capability_parity_registry.json"
parity = replace_strings(load(parity_path))
parity["authorities"]["current_production_runtime"] = f"deployed@{NEW}"
parity["authorities"]["current_production_code_commit"] = NEW
reanchor = parity["current_production_reanchor"]
reanchor["production_main_sha"] = NEW
reanchor["production_code_commit"] = NEW
reanchor["v3_topology"]["scheduler_runtime_self_heal_runtime_hardening_only"] = True
reanchor["control_plane_equivalence"]["scheduler_runtime_self_heal_contract"] = {
    "v5_owner": "orchestrator",
    "evidence": "config/v5_orchestrator_registry.json",
    "semantics": (
        "Current V3 scheduler watchdog, stale-runtime recovery workflow, cadence and concurrency hardening are operational reliability only. "
        "They do not change football, prediction, optimizer, or decision semantics and create no duplicate V5 execution authority."
    ),
}
parity.setdefault("governance", {})["v3_scheduler_runtime_self_heal_is_runtime_hardening_not_decision_authority"] = True
save(parity_path, parity)

status_path = "IMPLEMENTATION_STATUS.json"
status = replace_strings(load(status_path))
status["production_authority"]["main_sha"] = NEW
status["advanced_beta4"]["v3_scheduler_runtime_self_heal_reconciled"] = True
status["acceptance"]["release_fingerprint"] = "PENDING_REVALIDATION_AFTER_PRODUCTION_REANCHOR"
status["acceptance"]["fresh_postvalidated_real_shadow_cycles"] = 0
status["acceptance"]["operational_candidate_eligible"] = False
status["acceptance"]["prediction_candidate_eligible"] = False
status["acceptance"]["production_candidate_eligible"] = False
status["acceptance"]["production_promotion_allowed"] = False
notes = status.setdefault("notes", [])
scheduler_note = (
    "Current V3 scheduler watchdog and runtime self-heal changes at ef016111 are reconciled as operational runtime hardening only; "
    "they do not alter football, prediction, optimizer, decision, or V5 bounded-context authority."
)
if scheduler_note not in notes:
    notes.append(scheduler_note)
save(status_path, status)

for path in (manifest_path, acceptance_path, parity_path, status_path):
    text = Path(path).read_text(encoding="utf-8")
    if OLD in text:
        raise SystemExit(f"stale deployed production SHA remains in {path}")
print(f"Reanchored V5 metadata from {OLD} to deployed runtime {NEW}")
