from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one patch target in {path}, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_projection() -> None:
    path = ROOT / "src/v5/intelligence/projection.py"
    text = path.read_text(encoding="utf-8")
    required = (
        "        network_fixtures = []\n",
        "                if len(network_fixtures) < 5:\n",
        '                "fixtures": network_fixtures,\n',
        '        "network_contract": {\n',
    )
    for marker in required:
        if marker not in text:
            raise RuntimeError(f"projection baseline drift: missing {marker!r}")

    text = text.replace("        network_fixtures = []\n", "        fixture_summaries = []\n", 1)
    old = '''                if len(network_fixtures) < 5:\n                    network_fixtures.append(\n                        {\n                            "event": gw,\n                            "xpts": row["xpts"],\n                            "lower80": round(max(0.0, mean - 1.28 * std), 3),\n                            "upper80": round(mean + 1.28 * std, 3),\n                            "xmins": {\n                                key: xmins.get(key)\n                                for key in ("start_probability", "bench_probability", "dnp_probability", "expected_minutes")\n                            },\n                        }\n                    )\n'''
    new = '''                fixture_summaries.append(\n                    {\n                        "event": gw,\n                        "xpts": row["xpts"],\n                        "lower80": round(max(0.0, mean - 1.28 * std), 3),\n                        "upper80": round(mean + 1.28 * std, 3),\n                        "xmins": {\n                            key: xmins.get(key)\n                            for key in ("start_probability", "bench_probability", "dnp_probability", "expected_minutes")\n                        },\n                    }\n                )\n'''
    if text.count(old) != 1:
        raise RuntimeError("projection fixture compaction block drift")
    text = text.replace(old, new, 1)
    text = text.replace('                "fixtures": network_fixtures,\n', '                "fixtures": fixture_summaries,\n', 1)
    old_contract = '''        "players": players,\n        "network_contract": {\n            "bounded": True,\n            "max_fixture_rows_per_player": 5,\n            "full_provenance_omitted": True,\n        },\n'''
    if text.count(old_contract) != 1:
        raise RuntimeError("projection network contract block drift")
    text = text.replace(old_contract, '        "players": players,\n', 1)
    if "network_fixtures" in text or "max_fixture_rows_per_player" in text:
        raise RuntimeError("projection still contains transport-specific compaction authority")
    path.write_text(text, encoding="utf-8")


def patch_prediction_service() -> None:
    path = ROOT / "src/v5/services/prediction.py"
    text = path.read_text(encoding="utf-8")
    if 'SERVICE_CONFIG = "config/v5_prediction_service_registry.json"' in text:
        raise RuntimeError("prediction service patch already applied")
    marker = '\ndef _capabilities(enrichment:dict[str,Any]|None=None)->list[str]:\n'
    if text.count(marker) != 1:
        raise RuntimeError("prediction helper insertion marker drift")
    helpers = '''\nSERVICE_CONFIG = "config/v5_prediction_service_registry.json"\n\ndef _network_contract()->dict[str,Any]:\n    cfg=load_json_config(SERVICE_CONFIG); contract=cfg.get("network_contract")\n    if not isinstance(contract,dict): raise RuntimeError("V5 prediction network contract missing")\n    player_fields=contract.get("player_fields"); required=contract.get("required_player_fields"); fixture_fields=contract.get("fixture_fields"); fixture_count=contract.get("fixture_count")\n    if not isinstance(player_fields,list) or not player_fields or len(player_fields)!=len(set(player_fields)): raise RuntimeError("V5 prediction player_fields invalid")\n    if not isinstance(required,list) or not required or not set(required).issubset(set(player_fields)): raise RuntimeError("V5 prediction required_player_fields invalid")\n    if not isinstance(fixture_fields,list) or not fixture_fields or len(fixture_fields)!=len(set(fixture_fields)): raise RuntimeError("V5 prediction fixture_fields invalid")\n    if not isinstance(fixture_count,int) or isinstance(fixture_count,bool) or fixture_count<1: raise RuntimeError("V5 prediction fixture_count invalid")\n    if contract.get("return_full_predictions_by_default") is not False or contract.get("full_provenance_omitted") is not True: raise RuntimeError("V5 prediction network contract is not bounded")\n    if "element" not in required or "fixtures" not in required: raise RuntimeError("V5 prediction required contract fields incomplete")\n    return contract\n\ndef _compact_fixture(row:dict[str,Any],contract:dict[str,Any])->dict[str,Any]:\n    return {str(field):row.get(str(field)) for field in contract["fixture_fields"]}\n\ndef _compact_player(player:dict[str,Any],contract:dict[str,Any])->dict[str,Any]:\n    out={str(field):player.get(str(field)) for field in contract["player_fields"]}; fixtures=player.get("fixtures") if isinstance(player.get("fixtures"),list) else []; limit=int(contract["fixture_count"]); out["fixtures"]=[_compact_fixture(row,contract) for row in fixtures[:limit] if isinstance(row,dict)]; return out\n\ndef _published_network_contract(contract:dict[str,Any])->dict[str,Any]:\n    return {"bounded":True,"return_full_predictions_by_default":False,"player_fields":list(contract["player_fields"]),"required_player_fields":list(contract["required_player_fields"]),"fixture_count":int(contract["fixture_count"]),"fixture_fields":list(contract["fixture_fields"]),"full_provenance_omitted":True}\n'''
    text = text.replace(marker, helpers + marker, 1)
    start = text.find("    compact=[]\n")
    if start < 0:
        raise RuntimeError("prediction compact block start drift")
    ret = text.find("    return {", start)
    if ret < 0:
        raise RuntimeError("prediction compact block return drift")
    text = text[:start] + '    contract=_network_contract()\n    compact=[_compact_player(player,contract) for player in result.get("players") or [] if isinstance(player,dict)]\n' + text[ret:]
    old = '"network_contract":result.get("network_contract")'
    if text.count(old) != 1:
        raise RuntimeError("prediction published network contract marker drift")
    text = text.replace(old, '"network_contract":_published_network_contract(contract)', 1)
    path.write_text(text, encoding="utf-8")


def patch_registry() -> None:
    path = ROOT / "config/v5_prediction_service_registry.json"
    path.write_text('''{\n  "version": 2,\n  "default_operation": "build",\n  "network_contract": {\n    "return_full_predictions_by_default": false,\n    "full_provenance_omitted": true,\n    "player_fields": [\n      "element",\n      "name",\n      "team_id",\n      "position",\n      "now_cost",\n      "status",\n      "ownership_pct",\n      "current_season",\n      "historical_prior",\n      "xmins",\n      "role",\n      "xpts_by_gw",\n      "horizons",\n      "xpts_3",\n      "xpts_5",\n      "xpts_10",\n      "xpts_15",\n      "mean_xpts",\n      "uncertainty",\n      "fixtures",\n      "projection_confidence",\n      "advanced",\n      "tactical_matchup"\n    ],\n    "required_player_fields": [\n      "element",\n      "name",\n      "position",\n      "xmins",\n      "xpts_by_gw",\n      "horizons",\n      "xpts_3",\n      "xpts_5",\n      "xpts_10",\n      "xpts_15",\n      "mean_xpts",\n      "uncertainty",\n      "fixtures"\n    ],\n    "fixture_count": 5,\n    "fixture_fields": [\n      "event",\n      "xpts",\n      "lower80",\n      "upper80",\n      "xmins"\n    ]\n  },\n  "performance": {\n    "purpose": "bound prediction transport at the service boundary without mutating projection intelligence",\n    "parallel_safe": true\n  },\n  "governance": {\n    "single_network_contract_authority": true,\n    "projection_core_transport_agnostic": true,\n    "missing_or_invalid_contract_fails_closed": true\n  }\n}\n''', encoding="utf-8")


def patch_registry_catalog() -> None:
    path = ROOT / "config/v5_registry_catalog.json"
    text = path.read_text(encoding="utf-8")
    if '"prediction_network_contract"' in text:
        raise RuntimeError("prediction network contract catalog entry already exists")
    if '"version": 3' not in text:
        raise RuntimeError("registry catalog version drift")
    text = text.replace('"version": 3', '"version": 4', 1)
    marker = '    "projection_parameters": {"authority": "src/v5/intelligence/projection.py + config/intelligence/projection.json", "status": "ACTIVE"},\n'
    if text.count(marker) != 1:
        raise RuntimeError("registry catalog projection marker drift")
    text = text.replace(marker, marker + '    "prediction_network_contract": {"authority": "config/v5_prediction_service_registry.json", "runtime_enforcer": "src/v5/services/prediction.py", "status": "ACTIVE"},\n', 1)
    path.write_text(text, encoding="utf-8")


def patch_tests() -> None:
    path = ROOT / "tests/test_v5_microservices.py"
    text = path.read_text(encoding="utf-8")
    start = text.find("def test_prediction_network_contract_is_bounded_by_service_output_design():\n")
    if start < 0:
        raise RuntimeError("microservice network-contract test baseline drift")
    end = text.find("\ndef test_price_predictor_and_squeeze_have_exactly_one_price_service_owner():\n", start)
    if end < 0:
        raise RuntimeError("microservice network-contract test end drift")
    replacement = '''def test_prediction_network_contract_is_registry_driven_and_projection_core_is_transport_agnostic():\n    contract = load_json_config("config/v5_prediction_service_registry.json")["network_contract"]\n    source = (ROOT / "src/v5/services/prediction.py").read_text(encoding="utf-8")\n    core = (ROOT / "src/v5/intelligence/projection.py").read_text(encoding="utf-8")\n    fields = contract["player_fields"]\n    required = contract["required_player_fields"]\n    fixture_fields = contract["fixture_fields"]\n    assert contract["return_full_predictions_by_default"] is False\n    assert contract["full_provenance_omitted"] is True\n    assert contract["fixture_count"] == 5\n    assert len(fields) == len(set(fields))\n    assert len(fixture_fields) == len(set(fixture_fields))\n    assert set(required).issubset(set(fields))\n    assert {"element", "fixtures"}.issubset(set(required))\n    assert "rates" not in fields\n    assert "SERVICE_CONFIG" in source\n    assert "_compact_player" in source\n    assert "network_fixtures" not in core\n    assert "max_fixture_rows_per_player" not in core\n    assert '"network_contract"' not in core\n\n\ndef test_prediction_compactor_enforces_registry_fields_and_fixture_bound():\n    import src.v5.services.prediction as prediction_service\n\n    contract = prediction_service._network_contract()\n    player = {field: f"value:{field}" for field in contract["player_fields"]}\n    player["element"] = 1\n    player["rates"] = {"must_not_leak": True}\n    player["fixtures"] = [\n        {\n            "event": i + 1,\n            "xpts": 1.0,\n            "lower80": 0.0,\n            "upper80": 2.0,\n            "xmins": {"expected_minutes": 90},\n            "must_not_leak": True,\n        }\n        for i in range(int(contract["fixture_count"]) + 2)\n    ]\n    compact = prediction_service._compact_player(player, contract)\n    assert set(compact) == set(contract["player_fields"])\n    assert "rates" not in compact\n    assert len(compact["fixtures"]) == contract["fixture_count"]\n    assert all(set(row) == set(contract["fixture_fields"]) for row in compact["fixtures"])\n    assert all("must_not_leak" not in row for row in compact["fixtures"])\n'''
    text = text[:start] + replacement + text[end:]
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_registry()
    patch_registry_catalog()
    patch_projection()
    patch_prediction_service()
    patch_tests()
    print("V5 red hardening registry-authority patch applied")


if __name__ == "__main__":
    main()
