from __future__ import annotations

import argparse
import json
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


def run(
    *,
    config_path: Path = CONFIG_PATH,
    output_path: Path,
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
    args = parser.parse_args()
    result = run(config_path=args.config, output_path=args.output)
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
