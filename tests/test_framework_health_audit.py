import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def load(name):
    return json.loads((ROOT/'config'/name).read_text())


def test_dss_core_is_exactly_50_unique_modules():
    r=load('dss_core_registry.json'); rows=r['modules']
    assert len(rows)==50
    assert len({x['id'] for x in rows})==50
    assert [x['id'] for x in rows]==[f'DSS-{i:02d}' for i in range(1,51)]


def test_extensions_and_enhancement_counts_are_canonical():
    x=load('dss_extension_registry.json')['modules']
    e=load('enhancement_layers_registry.json')['layers']
    g=load('gate0_registry.json')['checks']
    assert len(x)==16 and len({r['id'] for r in x})==16
    assert len(e)==8 and [r['id'] for r in e]==[f'ENH-{i:02d}' for i in range(1,9)]
    assert len(g)==16 and [r['id'] for r in g]==[f'G0-{i:02d}' for i in range(1,17)]


def test_critical_framework_items_have_traceability():
    for filename,key in [
        ('dss_core_registry.json','modules'),
        ('dss_extension_registry.json','modules'),
        ('enhancement_layers_registry.json','layers'),
    ]:
        for row in load(filename)[key]:
            if row.get('critical'):
                assert row.get('required_files'), (filename,row['id'])


def test_every_dss_and_enhancement_item_has_operational_probe():
    for filename,key in [
        ('dss_core_registry.json','modules'),
        ('dss_extension_registry.json','modules'),
        ('enhancement_layers_registry.json','layers'),
    ]:
        for row in load(filename)[key]:
            assert row.get('operational_probe'), (filename,row['id'])


def test_file_presence_without_probe_is_never_active():
    from src.engines.framework_health_audit import _operational_probe

    status, detail = _operational_probe(None, 'postflight')
    assert status == 'PARTIAL'
    assert detail['reason'] == 'no operational probe declared'


def test_v47_prediction_quality_probes_reject_missing_output_evidence(monkeypatch):
    import src.engines.framework_health_audit as audit

    monkeypatch.setattr(audit, '_predictions', lambda: [])
    monkeypatch.setattr(audit, 'read_json', lambda *args, **kwargs: {})
    for probe in ('set_piece_role', 'penalty_role', 'opponent_defence_dynamic', 'last_season_integration'):
        status, _ = audit._operational_probe(probe, 'postflight')
        assert status != 'ACTIVE', probe


def test_registry_reuses_same_operational_probe_within_one_audit(monkeypatch):
    import src.engines.framework_health_audit as audit

    calls = []
    monkeypatch.setattr(audit, '_exists', lambda _: True)
    monkeypatch.setattr(audit, '_operational_probe', lambda name, phase: (calls.append((name, phase)) or ('ACTIVE', {})))
    audit._PROBE_CACHE = {}
    try:
        obj = {'registry': 'test', 'modules': [
            {'id': 'A', 'operational_probe': 'same'},
            {'id': 'B', 'operational_probe': 'same'},
        ]}
        result = audit._audit_registry('dss_core', obj, 'preflight')
        assert result['counts']['ACTIVE'] == 2
        assert calls == [('same', 'preflight')]
    finally:
        audit._PROBE_CACHE = None
