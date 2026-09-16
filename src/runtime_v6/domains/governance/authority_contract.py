from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class AuthorityContractError(RuntimeError):
    pass


V6_DATA_AUTHORITIES = {
    "data_acquisition",
    "normalization",
    "deterministic_identity",
    "validation",
    "cache_history",
    "provenance_lineage",
    "freshness_health",
    "publication",
}

FORBIDDEN_DOWNSTREAM_AUTHORITIES = {
    "decision",
    "prediction_authored_by_v6",
    "optimizer",
    "tactical",
    "transfer",
    "captain",
    "vice_captain",
    "chip",
    "formation",
    "xpts",
    "xmins",
    "p_start",
    "bayesian",
    "monte_carlo",
    "mini_league_analytics",
    "rank_probability",
}

CANONICAL_JOINABLE_IDENTITY_STATUSES = {"EXACT", "VERIFIED_MANUAL"}
NON_JOINABLE_IDENTITY_STATUSES = {"UNMAPPED", "AMBIGUOUS", "ORPHANED", "STALE"}

FORBIDDEN_V6_SEMANTIC_CLASSES = {
    "DECISION",
    "V6_PREDICTION",
    "OPTIMIZER_OUTPUT",
    "TACTICAL_RECOMMENDATION",
    "TRANSFER_RECOMMENDATION",
    "CAPTAIN_RECOMMENDATION",
    "CHIP_RECOMMENDATION",
    "FORMATION_RECOMMENDATION",
    "XPTS",
    "XMINS",
    "BAYESIAN_OUTPUT",
    "MONTE_CARLO_OUTPUT",
    "MINI_LEAGUE_ANALYTICS",
    "RANK_PROBABILITY",
}

ALLOWED_CANONICAL_SEMANTIC_CLASSES = {
    "FACT",
    "NORMALIZED_FACT",
    "IDENTITY_CROSSWALK",
    "CONTROL_TELEMETRY",
    "UPSTREAM_MODEL_SIGNAL",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AuthorityContractError(message)


def validate_schedule_policy(policy: dict[str, Any]) -> None:
    authorities = dict(policy.get("authorities") or {})
    missing_data = sorted(V6_DATA_AUTHORITIES - set(authorities))
    missing_forbidden = sorted(FORBIDDEN_DOWNSTREAM_AUTHORITIES - set(authorities))
    _require(not missing_data, f"missing V6 data authorities: {missing_data}")
    _require(not missing_forbidden, f"missing zero-authority declarations: {missing_forbidden}")

    wrong_data = sorted(name for name in V6_DATA_AUTHORITIES if authorities.get(name) != "V6")
    wrong_forbidden = sorted(
        name for name in FORBIDDEN_DOWNSTREAM_AUTHORITIES if authorities.get(name) != "NONE"
    )
    _require(not wrong_data, f"V6 data authority drift: {wrong_data}")
    _require(not wrong_forbidden, f"forbidden downstream authority claimed by V6: {wrong_forbidden}")

    governance = dict(policy.get("governance") or {})
    _require(governance.get("v6_is_fresh_data_only") is True, "V6 must remain fresh-data-only")
    _require(
        governance.get("v6_may_publish_decisions_or_predictions") is False,
        "V6 must not publish decisions or authored predictions",
    )
    _require(
        governance.get("v6_may_publish_mini_league_analytics") is False,
        "V6 must not publish canonical mini-league analytics",
    )
    _require(governance.get("atomic_facts_are_canonical") is True, "atomic facts must be canonical")

    identity = dict(governance.get("identity_join_policy") or {})
    _require(identity.get("silent_fuzzy_runtime_join_allowed") is False, "silent fuzzy joins are forbidden")
    _require(
        set(identity.get("allowed_statuses_for_canonical_join") or [])
        == CANONICAL_JOINABLE_IDENTITY_STATUSES,
        "canonical join statuses must be EXACT / VERIFIED_MANUAL only",
    )
    _require(
        set(identity.get("other_statuses") or []) == NON_JOINABLE_IDENTITY_STATUSES,
        "non-joinable identity status vocabulary drift",
    )


def validate_artifact_descriptor(descriptor: dict[str, Any]) -> None:
    canonical = descriptor.get("canonical") is not False
    semantic_class = str(descriptor.get("semantic_class") or "").upper()
    authority = str(descriptor.get("authority") or "").upper()

    if not canonical:
        _require(
            authority in {"", "NONE"},
            "noncanonical/deprecated artifacts must not retain V6 decision authority",
        )
        return

    _require(
        semantic_class not in FORBIDDEN_V6_SEMANTIC_CLASSES,
        f"forbidden canonical V6 semantic class: {semantic_class}",
    )
    if semantic_class:
        _require(
            semantic_class in ALLOWED_CANONICAL_SEMANTIC_CLASSES,
            f"unknown canonical semantic class must fail closed: {semantic_class}",
        )

    if semantic_class == "UPSTREAM_MODEL_SIGNAL":
        model_author = str(descriptor.get("model_author") or "").upper()
        v6_computation = str(descriptor.get("v6_computation") or "").upper()
        _require(model_author not in {"", "V6"}, "upstream model signal must identify a non-V6 author")
        _require(v6_computation == "NONE", "V6 must not author upstream model computations")


def validate_policy_file(path: Path) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), "schedule policy must be a JSON object")
    validate_schedule_policy(value)


def main() -> int:
    validate_policy_file(Path("config/v6/schedule_policy.json"))
    print("V6 authority contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
