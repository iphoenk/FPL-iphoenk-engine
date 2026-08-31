from __future__ import annotations

import os
import re
from typing import Any

from src.v5.config_cache import load_json_config

MANIFEST_CONFIG = "config/v5_convergence_manifest.json"
PRODUCTION_SOURCE_AUTHORITY = "runtime-data:data/runtime_manifest.json#source_commit"
PRODUCTION_SOURCE_ENV = "V5_PRODUCTION_SOURCE_SHA"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


def production_source_contract() -> dict[str, Any]:
    baseline = load_json_config(MANIFEST_CONFIG).get("baselines") or {}
    authority = str(baseline.get("production_source_authority") or "")
    environment = str(baseline.get("production_source_environment") or "")
    if authority != PRODUCTION_SOURCE_AUTHORITY:
        raise RuntimeError(f"unexpected V5 production source authority: {authority}")
    if environment != PRODUCTION_SOURCE_ENV:
        raise RuntimeError(f"unexpected V5 production source environment: {environment}")
    if baseline.get("production_main_sha") is not None or baseline.get("production_code_commit") is not None:
        raise RuntimeError("mutable deployed production SHA must not be pinned in V5 static metadata")
    return {"authority": authority, "environment": environment}


def production_source_sha(explicit: str | None = None) -> str:
    production_source_contract()
    value = str(explicit if explicit is not None else os.getenv(PRODUCTION_SOURCE_ENV, "")).strip().lower()
    if not _SHA40.fullmatch(value):
        raise RuntimeError(
            f"{PRODUCTION_SOURCE_ENV} must contain the exact 40-hex deployed runtime source_commit resolved from {PRODUCTION_SOURCE_AUTHORITY}"
        )
    return value
