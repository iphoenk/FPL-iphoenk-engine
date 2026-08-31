from pathlib import Path

from src.engines import v4_checkpoint_governance as governance


def _function_source(name: str, next_name: str) -> str:
    text = Path(governance.__file__).read_text(encoding="utf-8")
    return text.split(f"def {name}", 1)[1].split(f"def {next_name}", 1)[0]


def test_direct_governance_has_no_implicit_publication_artifact_reads():
    body = _function_source("govern_checkpoint", "run")
    for artifact in (
        "effective_plan_v4.json",
        "team.json",
        "tactical_serving_v4.json",
        "prices.json",
        "competitive_load_v4.json",
    ):
        assert f'read_json(DATA/"{artifact}"' not in body


def test_production_run_supplies_complete_publication_dependencies_explicitly():
    body = _function_source("run", "main")
    expected = {
        "effective_plan": "effective_plan_v4.json",
        "team": "team.json",
        "tactical": "tactical_serving_v4.json",
        "prices": "prices.json",
        "competitive": "competitive_load_v4.json",
    }
    for argument, artifact in expected.items():
        assert f'{argument}=read_json(DATA/"{artifact}"' in body


def test_partial_explicit_publication_dependency_set_is_rejected_by_source_contract():
    body = _function_source("govern_checkpoint", "run")
    assert "publication dependencies must be supplied together" in body
