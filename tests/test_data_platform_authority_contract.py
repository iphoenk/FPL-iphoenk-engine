from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.runtime_v6.authority_contract import (
    AuthorityContractError,
    validate_artifact_descriptor,
    validate_schedule_policy,
)


ROOT = Path(__file__).resolve().parents[1]


def test_schedule_policy_zero_authority_schema_is_fail_closed() -> None:
    policy = json.loads((ROOT / "config/v6/schedule_policy.json").read_text(encoding="utf-8"))
    validate_schedule_policy(policy)


def test_forbidden_v6_analytical_artifact_is_rejected() -> None:
    with pytest.raises(AuthorityContractError):
        validate_artifact_descriptor(
            {
                "canonical": True,
                "semantic_class": "MINI_LEAGUE_ANALYTICS",
                "authority": "V6",
            }
        )


def test_noncanonical_retired_artifact_has_no_authority() -> None:
    validate_artifact_descriptor(
        {
            "canonical": False,
            "semantic_class": "MINI_LEAGUE_ANALYTICS",
            "authority": "NONE",
        }
    )


def test_source_native_model_signal_is_legal_only_when_v6_does_not_author_it() -> None:
    validate_artifact_descriptor(
        {
            "canonical": True,
            "semantic_class": "UPSTREAM_MODEL_SIGNAL",
            "authority": "SOURCE_NATIVE",
            "model_author": "OFFICIAL_FPL_PRICE_PREDICTOR",
            "v6_computation": "NONE",
        }
    )
    with pytest.raises(AuthorityContractError):
        validate_artifact_descriptor(
            {
                "canonical": True,
                "semantic_class": "UPSTREAM_MODEL_SIGNAL",
                "authority": "V6",
                "model_author": "V6",
                "v6_computation": "AUTHORED",
            }
        )
