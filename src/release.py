from __future__ import annotations
from functools import lru_cache
from src.utils import CONFIG, read_json

@lru_cache(maxsize=1)
def release_manifest() -> dict:
    manifest = read_json(CONFIG / "release_manifest.json", {})
    if not manifest.get("release"):
        raise RuntimeError("release manifest missing release")
    return manifest

RELEASE_VERSION = str(release_manifest()["release"])
