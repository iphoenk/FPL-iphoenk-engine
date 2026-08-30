import json
import requests


def test_tmp_public_league_probe():
    r = requests.get('https://fantasy.premierleague.com/api/entry/3462711/', timeout=20)
    r.raise_for_status()
    entry = r.json()
    leagues = entry.get('leagues') or {}
    out = {
        'classic': [
            {
                'id': row.get('id'),
                'name': row.get('name'),
                'entry_rank': row.get('entry_rank'),
                'entry_last_rank': row.get('entry_last_rank'),
                'entry_can_leave': row.get('entry_can_leave'),
                'entry_can_admin': row.get('entry_can_admin'),
                'entry_can_invite': row.get('entry_can_invite'),
            }
            for row in (leagues.get('classic') or [])
        ],
        'h2h': [
            {
                'id': row.get('id'),
                'name': row.get('name'),
                'entry_rank': row.get('entry_rank'),
                'entry_last_rank': row.get('entry_last_rank'),
                'entry_can_leave': row.get('entry_can_leave'),
                'entry_can_admin': row.get('entry_can_admin'),
                'entry_can_invite': row.get('entry_can_invite'),
            }
            for row in (leagues.get('h2h') or [])
        ],
    }
    print('PUBLIC_LEAGUE_PROBE=' + json.dumps(out, ensure_ascii=False, separators=(',', ':')))
    assert False, 'intentional temporary probe'
