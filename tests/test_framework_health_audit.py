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
