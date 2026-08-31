from pathlib import Path
import json

root = Path('.')

# Predictor: preserve raw evidence health while exposing governed publication semantics.
path = root / 'src/engines/price_radar.py'
text = path.read_text(encoding='utf-8')
anchor = '''    else:\n        evidence_state = "REAL_ZERO" if current_progress == 0 else "AVAILABLE"\n        confidence = "HIGH"\n        fallback_reason = None\n\n    def projection_value(offset: int, key: str) -> Any:\n'''
replacement = '''    else:\n        evidence_state = "REAL_ZERO" if current_progress == 0 else "AVAILABLE"\n        confidence = "HIGH"\n        fallback_reason = None\n\n    if evidence_state in {"SCHEMA_CHANGED", "FIELD_MISSING"}:\n        predictor_serving_state = "UNAVAILABLE"\n    elif evidence_state == "STALE":\n        predictor_serving_state = "STALE"\n    elif cycle == "NONE":\n        predictor_serving_state = "NO_SIGNAL"\n    else:\n        predictor_serving_state = "AVAILABLE"\n\n    fetched_at_iso = observed_at.astimezone(timezone.utc).isoformat() if observed_at is not None else None\n    freshness_state = "UNAVAILABLE" if observed_at is None else "STALE" if stale else "FRESH"\n    trajectory_basis = {\n        "current_progress_percent": current_progress,\n        "price_change_hourly_rate": hourly_rate,\n        "projection_offsets": [0, 1, 2],\n        "model_threshold_percent": MODEL_THRESHOLD,\n        "predicted_change_cycle": cycle,\n    }\n\n    def projection_value(offset: int, key: str) -> Any:\n'''
if anchor not in text:
    raise SystemExit('price_radar state anchor not found')
text = text.replace(anchor, replacement, 1)
anchor = '''        "model_urgency": urgency,\n        "source": "OFFICIAL_FPL",\n        "observed_at": observed_at.astimezone(timezone.utc).isoformat() if observed_at is not None else None,\n        "freshness_seconds": freshness_seconds,\n'''
replacement = '''        "model_urgency": urgency,\n        "source": "OFFICIAL_FPL",\n        "provider": "OFFICIAL_FPL",\n        "observed_at": observed_at.astimezone(timezone.utc).isoformat() if observed_at is not None else None,\n        "fetched_at": fetched_at_iso,\n        "fetched_at_distinct": False,\n        "age_seconds": freshness_seconds,\n        "freshness_seconds": freshness_seconds,\n        "freshness_state": freshness_state,\n        "trajectory_basis": trajectory_basis,\n        "predictor_serving_state": predictor_serving_state,\n        "raw_evidence_state": evidence_state,\n'''
if anchor not in text:
    raise SystemExit('price_radar provenance anchor not found')
text = text.replace(anchor, replacement, 1)
anchor = '''        "predicted_change_cycle", "predicted_change_at", "model_urgency", "source", "observed_at",\n        "freshness_seconds", "schema_version", "raw_payload_hash", "confidence", "fallback_reason",\n        "evidence_state", "narrative",\n'''
replacement = '''        "predicted_change_cycle", "predicted_change_at", "model_urgency", "source", "provider", "observed_at",\n        "fetched_at", "fetched_at_distinct", "age_seconds", "freshness_seconds", "freshness_state",\n        "trajectory_basis", "predictor_serving_state", "raw_evidence_state",\n        "schema_version", "raw_payload_hash", "confidence", "fallback_reason", "evidence_state", "narrative",\n'''
if anchor not in text:
    raise SystemExit('price_radar served keys anchor not found')
text = text.replace(anchor, replacement, 1)
anchor = '''        "no_intra_cycle_crossing_eta": True,\n    }\n'''
replacement = '''        "no_intra_cycle_crossing_eta": True,\n        "publication_state_vocabulary": ["AVAILABLE", "NO_SIGNAL", "UNAVAILABLE", "STALE"],\n        "raw_evidence_state_preserved": True,\n    }\n'''
if anchor not in text:
    raise SystemExit('price_radar canonical contract anchor not found')
text = text.replace(anchor, replacement, 1)
path.write_text(text, encoding='utf-8')

# Canonical production health: publication failure cannot leave visible health GREEN.
path = root / 'src/services/governance_service.py'
text = path.read_text(encoding='utf-8')
anchor = '''    started = perf_counter()\n    checkpoint = v4_checkpoint_governance.run()\n    checkpoint_ms = round((perf_counter() - started) * 1000.0, 2)\n\n    out = {\n'''
replacement = '''    started = perf_counter()\n    try:\n        checkpoint = v4_checkpoint_governance.run()\n    except RuntimeError:\n        integrity = read_json(DATA / "publication_integrity_v4.json", {})\n        if integrity.get("status") == "BLOCKED":\n            maturity["publication_integrity"] = integrity\n            maturity["publication_integrity_health"] = "BLOCKED"\n            maturity["reporting_health"] = "BLOCKED"\n            maturity["serving_health"] = "BLOCKED"\n            maturity["overall"] = "RED"\n            maturity["production_health"] = "RED"\n            operational = maturity.setdefault("production_operational_health", {})\n            operational["status"] = "RED"\n            operational["operationally_ready"] = False\n            blockers = operational.setdefault("hard_blockers", [])\n            if "PUBLICATION_INTEGRITY_BLOCKED" not in blockers:\n                blockers.append("PUBLICATION_INTEGRITY_BLOCKED")\n            atomic_json(DATA / "framework_health_v4.json", maturity)\n        raise\n    checkpoint_ms = round((perf_counter() - started) * 1000.0, 2)\n\n    integrity = read_json(DATA / "publication_integrity_v4.json", {})\n    if integrity:\n        capabilities = integrity.get("capabilities") or {}\n        maturity["publication_integrity"] = integrity\n        maturity["publication_integrity_health"] = capabilities.get("publication_integrity") or integrity.get("status")\n        maturity["reporting_health"] = capabilities.get("reporting") or "UNAVAILABLE"\n        maturity["serving_health"] = capabilities.get("serving") or "UNAVAILABLE"\n        maturity.setdefault("governance", {}).update({\n            "publication_integrity_registered": True,\n            "publication_failure_cannot_leave_visible_health_green": True,\n        })\n        if integrity.get("status") != "PASS":\n            maturity["overall"] = "RED"\n            maturity["production_health"] = "RED"\n            operational = maturity.setdefault("production_operational_health", {})\n            operational["status"] = "RED"\n            operational["operationally_ready"] = False\n            blockers = operational.setdefault("hard_blockers", [])\n            if "PUBLICATION_INTEGRITY_BLOCKED" not in blockers:\n                blockers.append("PUBLICATION_INTEGRITY_BLOCKED")\n        atomic_json(DATA / "framework_health_v4.json", maturity)\n\n    out = {\n'''
if anchor not in text:
    raise SystemExit('governance checkpoint anchor not found')
text = text.replace(anchor, replacement, 1)
anchor = '''            "report_governance": checkpoint.get("action_state"),\n        },\n'''
replacement = '''            "report_governance": checkpoint.get("action_state"),\n            "publication_integrity": (integrity.get("capabilities") or {}).get("publication_integrity") or integrity.get("status") or "UNAVAILABLE",\n        },\n'''
if anchor not in text:
    raise SystemExit('governance component anchor not found')
text = text.replace(anchor, replacement, 1)
path.write_text(text, encoding='utf-8')

# Registry: publication integrity is a governance-owned contract, not an unregistered sidecar.
path = root / 'config/service_registry.json'
registry = json.loads(path.read_text(encoding='utf-8'))
registry['schema_version'] = max(int(registry.get('schema_version') or 0), 13)
registry['registry'] = 'fpl_v4_9_6_microservice_registry_v13'
governance = next(row for row in registry['services'] if row['id'] == 'governance')
if 'publication_integrity' not in governance['produces']:
    governance['produces'].append('publication_integrity')
registry.setdefault('guardrails', {}).update({
    'publication_integrity_registered': True,
    'publication_failure_cannot_leave_green_visible_health': True,
    'predictor_publication_state_explicit': True,
})
path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

path = root / 'config/service_contract_registry.json'
contracts = json.loads(path.read_text(encoding='utf-8'))
contracts['schema_version'] = max(int(contracts.get('schema_version') or 0), 10)
contracts['registry'] = 'fpl_v4_9_6_service_contracts_v10'
contracts['contracts']['publication_integrity'] = {
    'path': 'data/publication_integrity_v4.json',
    'min_schema_version': 1,
    'required_paths': [
        'contract', 'status', 'factual_gate_pass',
        'owned.expected', 'owned.resolved', 'owned.official_fact_complete',
        'watchlist.expected', 'watchlist.resolved', 'watchlist.official_fact_complete',
        'watchlist.position_counts.GK', 'watchlist.position_counts.DEF',
        'watchlist.position_counts.MID', 'watchlist.position_counts.FWD',
        'watchlist.position_cardinality_exact', 'watchlist.owned_overlap',
        'official_snapshot.single_coherent_snapshot',
        'capabilities.publication_integrity', 'capabilities.reporting',
        'capabilities.serving', 'capabilities.overall',
        'authority_separation.execution_authorized_semantics_unchanged'
    ],
    'equals': {
        'contract': 'V4_OFFICIAL_FACT_PUBLICATION_INTEGRITY_V1',
        'status': 'PASS',
        'factual_gate_pass': True,
        'watchlist.position_cardinality_exact': True,
        'official_snapshot.single_coherent_snapshot': True,
        'capabilities.publication_integrity': 'PASS',
        'capabilities.reporting': 'PASS',
        'capabilities.serving': 'PASS',
        'capabilities.overall': 'PASS',
        'authority_separation.execution_authorized_semantics_unchanged': True
    }
}
path.write_text(json.dumps(contracts, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

# QA: prove actual served predictor states/provenance, not static strings.
path = root / 'tests/test_v4_official_price_predictor.py'
text = path.read_text(encoding='utf-8')
if '_served_evidence,' not in text:
    text = text.replace('    _scheduled_update,\n    canonical_contract,\n', '    _scheduled_update,\n    _served_evidence,\n    canonical_contract,\n', 1)
addition = r'''


def test_predictor_publication_states_and_provenance_are_explicit():
    now = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
    no_signal = _normalise(_player(
        price_change_percent=34.3,
        price_change_projections=[
            {"offset": 0, "projected_percent": 39.8, "likelihood": 1},
            {"offset": 1, "projected_percent": 45.0, "likelihood": 1},
            {"offset": 2, "projected_percent": 50.0, "likelihood": 1},
        ],
    ), now=now)
    served = _served_evidence(no_signal, owned=False)
    assert served["predictor_serving_state"] == "NO_SIGNAL"
    assert served["raw_evidence_state"] == "AVAILABLE"
    assert served["provider"] == "OFFICIAL_FPL"
    assert served["observed_at"] == served["fetched_at"]
    assert served["fetched_at_distinct"] is False
    assert served["age_seconds"] == served["freshness_seconds"]
    assert served["freshness_state"] == "FRESH"
    assert served["trajectory_basis"]["current_progress_percent"] == 34.3
    assert served["trajectory_basis"]["model_threshold_percent"] == MODEL_THRESHOLD

    stale = _normalise(_player(element=2), now=now, observed_at=now - timedelta(hours=3))
    stale_served = _served_evidence(stale, owned=False)
    assert stale_served["predictor_serving_state"] == "STALE"
    assert stale_served["freshness_state"] == "STALE"
    assert stale_served["age_seconds"] == 10800

    unavailable_player = _player(element=3)
    unavailable_player.pop("price_change_percent")
    unavailable = _normalise(unavailable_player, now=now)
    assert _served_evidence(unavailable, owned=False)["predictor_serving_state"] == "UNAVAILABLE"

    actionable = _normalise(_player(element=4), now=now)
    assert _served_evidence(actionable, owned=False)["predictor_serving_state"] == "AVAILABLE"
'''
if 'test_predictor_publication_states_and_provenance_are_explicit' not in text:
    text += addition
path.write_text(text, encoding='utf-8')

# QA registry contract.
path = root / 'tests/test_v4_official_fact_completeness_p0.py'
text = path.read_text(encoding='utf-8')
addition = r'''


def test_publication_integrity_is_registered_as_governance_contract():
    import json
    from src.utils import CONFIG

    services = json.loads((CONFIG / "service_registry.json").read_text(encoding="utf-8"))
    contracts = json.loads((CONFIG / "service_contract_registry.json").read_text(encoding="utf-8"))
    governance = next(row for row in services["services"] if row["id"] == "governance")
    assert "publication_integrity" in governance["produces"]
    contract = contracts["contracts"]["publication_integrity"]
    assert contract["path"] == "data/publication_integrity_v4.json"
    assert contract["equals"]["status"] == "PASS"
    assert services["guardrails"]["publication_failure_cannot_leave_green_visible_health"] is True
'''
if 'test_publication_integrity_is_registered_as_governance_contract' not in text:
    text += addition
path.write_text(text, encoding='utf-8')
