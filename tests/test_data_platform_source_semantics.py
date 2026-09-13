from __future__ import annotations

import json
from pathlib import Path

from src.runtime_v6.registry import load_registry

ROOT = Path(__file__).resolve().parents[1]
ACTIVATION = ROOT / "config" / "v6" / "source_activation.json"
CANDIDATES = ROOT / "config" / "v6" / "structured_source_candidates.json"

FORBIDDEN_ACTIVE_CATEGORY_TOKENS = (
    "model",
    "editorial",
    "tactical",
    "prediction",
    "optimizer",
    "recommendation",
)

FPL_MASTER_ONLY_SOURCE_IDS = {
    "onside",
    "ben_crellin",
    "fffix",
    "ffhub",
    "onefpl",
    "livefpl",
    "ffscout",
    "solio_analytics",
    "check_the_chance",
    "fantasy_football_pundit",
    "bbc_team_news",
    "premier_injuries",
    "fpl_form",
    "fpl_review_free",
}


def test_active_v6_sources_remain_data_only_by_category() -> None:
    registry = load_registry()
    for source in registry["sources"]:
        category = str(source.get("category") or "").lower()
        assert not any(token in category for token in FORBIDDEN_ACTIVE_CATEGORY_TOKENS), (
            source["id"],
            category,
        )


def test_model_editorial_sources_are_not_active_v6_runtime_sources() -> None:
    registry = load_registry()
    active_ids = {str(source["id"]) for source in registry["sources"]}
    assert not active_ids.intersection(FPL_MASTER_ONLY_SOURCE_IDS)

    activation = json.loads(ACTIVATION.read_text(encoding="utf-8"))
    reference_only = set((activation.get("reference_only_sources") or {}).keys())
    assert FPL_MASTER_ONLY_SOURCE_IDS.issubset(reference_only)


def test_wave_a_candidate_catalog_is_fail_closed() -> None:
    payload = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    assert payload["ownership"] == "V6_DATA_ONLY"
    rules = payload["promotion_rule"]
    assert rules["requires_public_no_auth_access"] is True
    assert rules["requires_stable_retrieval_contract"] is True
    assert rules["requires_factual_field_allowlist"] is True
    assert rules["requires_deterministic_identity_path_for_player_level_data"] is True
    assert rules["forbids_model_prediction_optimizer_editorial_fields"] is True
    assert rules["mixed_sources_require_field_level_extractor_before_activation"] is True
    assert rules["name_or_fuzzy_join_forbidden"] is True

    candidates = payload["candidates"]
    ids = [row["id"] for row in candidates]
    assert len(ids) == len(set(ids))

    for row in candidates:
        status = str(row["status"])
        if "MIXED_SOURCE" in status or "FIELD_EXTRACTOR" in status:
            assert row["semantic_class"].startswith("MIXED_SOURCE_")


def test_wave_a_does_not_promote_unvalidated_candidates() -> None:
    registry = load_registry()
    active_ids = {str(source["id"]) for source in registry["sources"]}
    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))["candidates"]
    staged_ids = {
        row["id"]
        for row in candidates
        if row["status"] not in {"EXISTING_ACTIVE_STRUCTURED"}
    }
    assert not active_ids.intersection(staged_ids)
