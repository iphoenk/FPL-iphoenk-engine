from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = ROOT / "config" / "v6" / "entity_scope_policy.json"


class EntityScopePolicyError(ValueError):
    pass


@lru_cache(maxsize=4)
def load_entity_scope_policy(path: str | None = None) -> dict[str, Any]:
    policy_path = Path(path) if path else DEFAULT_POLICY
    payload = json.loads(policy_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise EntityScopePolicyError("unsupported V6 entity-scope policy schema")
    allowed = {str(value) for value in payload.get("allowed_scopes") or []}
    if not allowed:
        raise EntityScopePolicyError("entity-scope policy has no allowed scopes")
    for source, scopes in dict(payload.get("source_overrides") or {}).items():
        unknown = sorted({str(scope) for scope in scopes} - allowed)
        if unknown:
            raise EntityScopePolicyError(f"unknown scopes for source {source}: {unknown}")
    for category, scopes in dict(payload.get("category_defaults") or {}).items():
        unknown = sorted({str(scope) for scope in scopes} - allowed)
        if unknown:
            raise EntityScopePolicyError(f"unknown scopes for category {category}: {unknown}")
    return payload


def entity_scopes_for_source(source: dict[str, Any], policy: dict[str, Any] | None = None) -> list[str]:
    policy = policy or load_entity_scope_policy()
    allowed = {str(value) for value in policy.get("allowed_scopes") or []}
    explicit = source.get("entity_scopes")
    if isinstance(explicit, list) and explicit:
        scopes = [str(scope) for scope in explicit]
    else:
        source_id = str(source.get("id") or "")
        category = str(source.get("category") or "")
        overrides = dict(policy.get("source_overrides") or {})
        defaults = dict(policy.get("category_defaults") or {})
        scopes = [str(scope) for scope in overrides.get(source_id, defaults.get(category, ["FEED"]))]
    unknown = sorted(set(scopes) - allowed)
    if unknown:
        raise EntityScopePolicyError(f"source {source.get('id')} has unknown entity scopes: {unknown}")
    return sorted(dict.fromkeys(scopes))


def source_scope_map(config: dict[str, Any]) -> dict[str, list[str]]:
    policy = load_entity_scope_policy()
    return {
        str(source["id"]): entity_scopes_for_source(source, policy)
        for source in config.get("sources") or []
    }
