from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_MAX_AGE_MINUTES = 90
MAX_CLOCK_SKEW_MINUTES = 5


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assess_snapshot(
    root: Path | str = Path("data/v6"),
    *,
    now: datetime | None = None,
    max_age_minutes: int = DEFAULT_MAX_AGE_MINUTES,
) -> dict[str, Any]:
    root = Path(root)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    failures: list[str] = []

    manifest_path = root / "manifest.json"
    integrity_path = root / "health" / "publish_integrity.json"
    if not manifest_path.exists():
        return {
            "state": "INVALID",
            "usable": False,
            "direct_fallback_eligible": True,
            "failures": ["MISSING_MANIFEST"],
        }
    if not integrity_path.exists():
        return {
            "state": "INVALID",
            "usable": False,
            "direct_fallback_eligible": True,
            "failures": ["MISSING_PUBLISH_INTEGRITY"],
        }

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "state": "INVALID",
            "usable": False,
            "direct_fallback_eligible": True,
            "failures": [f"UNREADABLE_RUNTIME:{type(exc).__name__}"],
        }

    governance = manifest.get("governance") or {}
    if governance.get("data_only") is not True:
        failures.append("DATA_ONLY_CONTRACT_BROKEN")
    for authority in ("decision_authority", "prediction_authority", "optimizer_authority"):
        if governance.get(authority) != "NONE":
            failures.append(f"UNEXPECTED_{authority.upper()}")

    if integrity.get("status") != "PASS":
        failures.append("PUBLISH_INTEGRITY_NOT_PASS")
    if integrity.get("current_source_files_exact") is not True:
        failures.append("CURRENT_SOURCE_FILESET_NOT_EXACT")
    if integrity.get("identity_map_consistent") is not True:
        failures.append("IDENTITY_MAP_NOT_CONSISTENT")

    generated_at_raw = manifest.get("generated_at")
    if not generated_at_raw:
        failures.append("MISSING_GENERATED_AT")
        generated_at = None
        age_minutes = None
    else:
        try:
            generated_at = _utc(str(generated_at_raw))
            age_minutes = (now - generated_at).total_seconds() / 60.0
            if age_minutes < -MAX_CLOCK_SKEW_MINUTES:
                failures.append("GENERATED_AT_IN_FUTURE")
        except (TypeError, ValueError):
            generated_at = None
            age_minutes = None
            failures.append("INVALID_GENERATED_AT")

    control = manifest.get("runtime_control") or {}
    if manifest.get("overall") == "RED":
        failures.append("MANIFEST_OVERALL_RED")
    if control.get("health") == "RED":
        failures.append("RUNTIME_CONTROL_RED")
    for failure in manifest.get("critical_failures") or []:
        failures.append(f"CRITICAL:{failure}")
    for failure in manifest.get("control_failures") or []:
        failures.append(f"CONTROL:{failure}")

    if failures:
        state = "INVALID"
        usable = False
        fallback = True
    elif age_minutes is None:
        state = "INVALID"
        usable = False
        fallback = True
    elif age_minutes > float(max_age_minutes):
        state = "STALE"
        usable = False
        fallback = True
    else:
        state = "FRESH"
        usable = True
        fallback = False

    return {
        "state": state,
        "usable": usable,
        "direct_fallback_eligible": fallback,
        "generated_at": generated_at.isoformat() if generated_at else None,
        "evaluated_at": now.isoformat(),
        "age_minutes": round(age_minutes, 3) if age_minutes is not None else None,
        "max_age_minutes": int(max_age_minutes),
        "manifest_overall": manifest.get("overall"),
        "runtime_control_health": control.get("health"),
        "failures": failures,
        "governance": {
            "consumer_does_not_trust_static_green_without_freshness": True,
            "stale_or_invalid_allows_minimum_scope_direct_fallback": True,
            "fresh_v6_is_primary_data_authority": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Assess whether the latest V6 runtime snapshot is safe to consume")
    parser.add_argument("--root", default="data/v6")
    parser.add_argument("--max-age-minutes", type=int, default=DEFAULT_MAX_AGE_MINUTES)
    args = parser.parse_args()
    result = assess_snapshot(args.root, max_age_minutes=args.max_age_minutes)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["usable"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
