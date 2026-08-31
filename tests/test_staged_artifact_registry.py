from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE_REGISTRY = ROOT / "config" / "v3_service_registry.json"
OWNERSHIP_REGISTRY = ROOT / "config" / "v3_architecture_ownership_registry.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact_writers(services: dict) -> dict[str, set[str]]:
    writers: dict[str, set[str]] = defaultdict(set)
    for service, spec in services.items():
        for artifact in spec.get("artifacts") or []:
            writers[str(artifact)].add(str(service))
    return writers


def _ancestors(service: str, services: dict) -> set[str]:
    result: set[str] = set()
    stack = list((services.get(service) or {}).get("depends_on") or [])
    while stack:
        current = str(stack.pop())
        if current in result:
            continue
        result.add(current)
        stack.extend((services.get(current) or {}).get("depends_on") or [])
    return result


def test_staged_artifact_registry_exactly_matches_active_multiwriters():
    service_registry = _load(SERVICE_REGISTRY)
    ownership_registry = _load(OWNERSHIP_REGISTRY)
    services = service_registry["services"]

    active_multiwriters = {
        artifact: writers
        for artifact, writers in _artifact_writers(services).items()
        if len(writers) > 1
    }
    declared = ownership_registry.get("declared_staged_artifacts") or {}

    assert set(declared) == set(active_multiwriters), (
        "staged artifact declarations must be an exact projection of active multiwriters; "
        f"declared_only={sorted(set(declared) - set(active_multiwriters))} "
        f"undeclared={sorted(set(active_multiwriters) - set(declared))}"
    )

    for artifact, actual_writers in active_multiwriters.items():
        spec = declared[artifact]
        allowed_writers = {str(value) for value in spec.get("allowed_writers") or []}
        final_owner = str(spec.get("final_owner") or "")

        assert allowed_writers == actual_writers, (
            f"{artifact} allowed_writers drift: "
            f"declared={sorted(allowed_writers)} actual={sorted(actual_writers)}"
        )
        assert final_owner in actual_writers, f"{artifact} final_owner is not an active writer: {final_owner}"

        upstream = actual_writers - {final_owner}
        final_owner_ancestors = _ancestors(final_owner, services)
        assert upstream <= final_owner_ancestors, (
            f"{artifact} final owner must execute after every upstream writer; "
            f"final_owner={final_owner} missing_ancestors={sorted(upstream - final_owner_ancestors)}"
        )


def test_only_intentional_v3_multiwriters_remain():
    services = _load(SERVICE_REGISTRY)["services"]
    active = {
        artifact: sorted(writers)
        for artifact, writers in _artifact_writers(services).items()
        if len(writers) > 1
    }
    assert active == {
        "prices.json": ["market_state", "price"],
        "user_report.json": ["report_materializer", "reporting"],
    }
