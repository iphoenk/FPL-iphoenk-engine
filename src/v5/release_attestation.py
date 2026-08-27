from __future__ import annotations
import hashlib
import json
from functools import lru_cache
from typing import Any

from src.v5 import V5_VERSION
from src.v5.config_cache import load_json_config
from src.v5.release_integrity import runtime_fingerprint

CONFIG = "config/v5_release_attestation_registry.json"
MANIFEST = "config/v5_convergence_manifest.json"

@lru_cache(maxsize=1)
def release_attestation() -> dict[str, Any]:
    cfg=load_json_config(CONFIG); manifest=load_json_config(MANIFEST); baseline=manifest.get("baselines") or {}; release=runtime_fingerprint()
    payload={"contract":cfg.get("contract"),"v5_version":V5_VERSION,"production_baseline_version":baseline.get("production_truth"),"production_main_sha":baseline.get("production_main_sha"),"runtime_release_fingerprint":release.get("fingerprint")}
    canonical=json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8"); attestation="sha256:"+hashlib.sha256(canonical).hexdigest()
    return {**payload,"attestation":attestation,"algorithm":"sha256","promotion_authority":False}
