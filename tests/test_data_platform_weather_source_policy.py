import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_json(relative_path: str) -> dict:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def test_open_meteo_is_retired_from_v6_runtime_sources() -> None:
    activation = _load_json("config/v6/source_activation.json")

    disabled = activation.get("disabled_sources", {})
    assert "open_meteo" in disabled
    assert "CHATGPT" in disabled["open_meteo"].upper()
    assert "open_meteo" not in activation.get("required_active_sources", [])
    assert "open_meteo" not in activation.get("constraints", {})
    assert "open_meteo" not in activation.get("tiers", {})
