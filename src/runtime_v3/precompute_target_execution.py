from __future__ import annotations

import json
import os
from typing import Any

from src.utils import ROOT

PROFILE_POLICY_PATH = ROOT / "config" / "runtime" / "execution_profile_policy.json"
SHARD_POLICY_PATH = ROOT / "config" / "runtime" / "package_optimizer_sharding.json"


def _load_json(path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_target_execution(visible_mode: str) -> dict[str, Any]:
    profile_policy = _load_json(PROFILE_POLICY_PATH)
    if profile_policy.get("registry") != "V3_EXECUTION_PROFILE_POLICY_V1":
        raise RuntimeError("unexpected V3 execution profile policy")
    sharding = _load_json(SHARD_POLICY_PATH)
    if sharding.get("registry") != "V3_PACKAGE_OPTIMIZER_SHARDING_V1":
        raise RuntimeError("unexpected V3 package optimizer sharding policy")

    modes = profile_policy.get("visible_modes") or {}
    default = profile_policy.get("default") or {}
    selected = modes.get(str(visible_mode or ""))
    if not isinstance(selected, dict):
        selected = default
        selected_key = "DEFAULT"
    else:
        selected_key = str(visible_mode)

    profile = str(selected.get("profile") or default.get("profile") or "")
    mode = str(selected.get("mode") or default.get("mode") or "")
    extra = str(selected.get("extra") or "")
    authority_profile = str(((sharding.get("workflow") or {}).get("authority_profile")) or "")
    if not profile or mode not in {"daily", "deadline", "live"} or not authority_profile:
        raise RuntimeError("target execution mapping is incomplete")
    if extra not in {"", "--deep-stats"}:
        raise RuntimeError(f"unsupported registry target execution extra: {extra}")

    return {
        "selected_mode_key": selected_key,
        "target_visible_mode": str(visible_mode or "SILENT"),
        "seed_profile": profile,
        "execution_mode": mode,
        "execution_extra": extra,
        "deep_stats": extra == "--deep-stats",
        "authority_profile": authority_profile,
        "governance": {
            "target_semantics_registry_driven": True,
            "workflow_does_not_reimplement_visible_mode_mapping": True,
            "exhaustive_authority_profile_registry_driven": True,
        },
    }


def _append_outputs(result: dict[str, Any]) -> None:
    output = os.getenv("GITHUB_OUTPUT")
    if not output:
        return
    values = {
        "seed_profile": result["seed_profile"],
        "execution_mode": result["execution_mode"],
        "execution_extra": result["execution_extra"],
        "deep_stats": "true" if result["deep_stats"] else "false",
        "authority_profile": result["authority_profile"],
        "selected_mode_key": result["selected_mode_key"],
    }
    with open(output, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def main() -> int:
    result = resolve_target_execution(os.getenv("FPL_TARGET_VISIBLE_MODE", "SILENT"))
    _append_outputs(result)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
