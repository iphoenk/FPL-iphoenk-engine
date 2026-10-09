from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.sources.camoufox_transport import CaptureTarget, capture_targets
from src.utils import ROOT


CONFIG_PATH = ROOT / "config" / "sources" / "camoufox_public_sources.json"


def _load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_targets(config: dict[str, Any]) -> list[CaptureTarget]:
    targets: list[CaptureTarget] = []
    seen: set[tuple[str, str]] = set()
    for source in config.get("sources") or []:
        if not isinstance(source, dict) or source.get("enabled") is not True:
            continue
        source_id = str(source.get("source_id") or "").strip()
        source_class = str(source.get("source_class") or "").strip()
        purpose = tuple(str(value) for value in source.get("purpose") or [])
        if not source_id or not source_class:
            continue
        for raw_url in source.get("urls") or []:
            url = str(raw_url or "").strip()
            key = (source_id, url)
            if not url or key in seen:
                continue
            seen.add(key)
            targets.append(
                CaptureTarget(
                    source_id=source_id,
                    source_class=source_class,
                    url=url,
                    purpose=purpose,
                )
            )
    return targets


def _parse_aware(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _write(output_path: Path, result: dict[str, Any]) -> dict[str, Any]:
    result["report_slot"] = report_slot
    return _write(output_path, result)


def run(
    *,
    config_path: Path = CONFIG_PATH,
    output_path: Path,
    report_slot: str | None = None,
    max_slot_lag_minutes: int = 90,
    now: datetime | None = None,
) -> dict[str, Any]:
    config = _load_config(config_path)
    if config.get("contract") != "CAMOUFOX_PUBLIC_INFORMATION_ACQUISITION_V1":
        raise RuntimeError("invalid_camoufox_source_contract")

    policy = dict(config.get("policy") or {})
    required_true = (
        "public_read_only",
        "authentication_forbidden",
        "member_or_paywalled_pages_forbidden",
        "captcha_solving_forbidden",
        "official_fpl_api_remains_direct",
        "structured_api_and_csv_sources_remain_direct",
        "raw_capture_never_mutates_dss_or_model",
        "raw_capture_never_becomes_verified_fact_without_existing_evidence_validation",
        "source_failure_is_non_blocking",
    )
    missing = [key for key in required_true if policy.get(key) is not True]
    if missing:
        raise RuntimeError("unsafe_camoufox_policy:" + ",".join(sorted(missing)))

    slot = _parse_aware(report_slot)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if report_slot:
        if slot is None:
            return _write(
                output_path,
                {
                    "schema_version": 1,
                    "contract": "report_time_web_capture_v1",
                    "generated_at": current.isoformat(),
                    "status": "SKIPPED_INVALID_REPORT_SLOT",
                    "transport": "CAMOUFOX",
                    "report_slot": report_slot,
                    "capture_count": 0,
                    "available_count": 0,
                    "captures": [],
                    "governance": {
                        "historical_replay_must_not_use_live_web": True,
                        "report_delivery_blocking": False,
                    },
                },
            )
        lag_minutes = (current - slot).total_seconds() / 60.0
        if lag_minutes > max(1, int(max_slot_lag_minutes)) or lag_minutes < -5:
            return _write(
                output_path,
                {
                    "schema_version": 1,
                    "contract": "report_time_web_capture_v1",
                    "generated_at": current.isoformat(),
                    "status": "SKIPPED_HISTORICAL_OR_FUTURE_SLOT",
                    "transport": "CAMOUFOX",
                    "report_slot": report_slot,
                    "slot_lag_minutes": round(lag_minutes, 3),
                    "capture_count": 0,
                    "available_count": 0,
                    "captures": [],
                    "governance": {
                        "historical_replay_must_not_use_live_web": True,
                        "report_delivery_blocking": False,
                    },
                },
            )

    defaults = dict(config.get("defaults") or {})
    result = capture_targets(
        build_targets(config),
        navigation_timeout_seconds=float(
            defaults.get("navigation_timeout_seconds") or 18
        ),
        settle_milliseconds=int(defaults.get("settle_milliseconds") or 750),
        max_visible_text_chars=int(
            defaults.get("max_visible_text_chars") or 120000
        ),
    )
    result["source_contract"] = config.get("contract")
    result["governance"] = {
        "official_fpl_api_transport": "DIRECT_UNCHANGED",
        "structured_api_csv_transport": "DIRECT_UNCHANGED",
        "dss_mutation": False,
        "model_mutation": False,
        "verified_fact_promotion": False,
        "report_delivery_blocking": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report-slot", default="")
    parser.add_argument("--max-slot-lag-minutes", type=int, default=90)
    args = parser.parse_args()
    result = run(
        config_path=args.config,
        output_path=args.output,
        report_slot=args.report_slot or None,
        max_slot_lag_minutes=args.max_slot_lag_minutes,
    )
    print(
        json.dumps(
            {
                "status": result.get("status"),
                "capture_count": result.get("capture_count"),
                "available_count": result.get("available_count"),
                "transport": result.get("transport"),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
