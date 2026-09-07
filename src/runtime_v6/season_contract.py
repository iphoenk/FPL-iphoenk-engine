from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SEASON_CONTRACT = ROOT / "config" / "v6" / "season_contract.json"
_TOKEN = re.compile(r"\{\{season\.([a-z_]+)\}\}")


class SeasonContractError(ValueError):
    pass


def load_season_contract(path: Path = DEFAULT_SEASON_CONTRACT) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SeasonContractError(f"invalid V6 season contract: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise SeasonContractError("V6 season contract schema_version must be 1")
    try:
        start = int(payload["start_year"])
        end = int(payload["end_year"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SeasonContractError("V6 season contract requires integer start_year/end_year") from exc
    if end != start + 1:
        raise SeasonContractError("V6 season contract must describe one consecutive football season")
    competition = str(payload.get("competition") or "").strip()
    if not competition:
        raise SeasonContractError("V6 season contract requires competition")

    start_short = str(start)[-2:]
    end_short = str(end)[-2:]
    values = {
        "competition": competition,
        "start_year": str(start),
        "end_year": str(end),
        "end_year_short": end_short,
        "canonical": f"{start}-{end}",
        "slash_full": f"{start}/{end}",
        "slash_short": f"{start}/{end_short}",
        "hyphen_short": f"{start}-{end_short}",
        "compact_short": f"{start_short}{end_short}",
    }
    return {
        "schema_version": 1,
        "competition": competition,
        "start_year": start,
        "end_year": end,
        "values": values,
    }


def _materialize(value: Any, values: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _materialize(child, values) for key, child in value.items()}
    if isinstance(value, list):
        return [_materialize(child, values) for child in value]
    if not isinstance(value, str):
        return deepcopy(value)

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise SeasonContractError(f"unknown V6 season token: {key}")
        return values[key]

    rendered = _TOKEN.sub(replace, value)
    if "{{season." in rendered:
        raise SeasonContractError(f"unresolved V6 season token: {rendered}")
    return rendered


def materialize_season_tokens(
    payload: dict[str, Any],
    *,
    path: Path = DEFAULT_SEASON_CONTRACT,
) -> dict[str, Any]:
    contract = load_season_contract(path)
    return _materialize(payload, dict(contract["values"]))
