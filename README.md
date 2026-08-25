# FPL iphoenk Engine

Read-only FPL public-data collector for Team ID **3462711**.

## What it does

- Pulls direct public FPL API data
- Auto-detects current / next Gameweek
- Produces an endpoint-health state
- Resolves team-specific public picks
- Builds a public purchase/sell-value ledger where ownership-spell data is reconstructable
- Tracks used chips
- Produces provisional live team score during a live GW
- Exports the full API-first FPL player universe
- Persists `data/latest.json` plus a compact `data/history.jsonl`

## Public bridge URL

After this repository is public, the Master Monitor can read:

`https://raw.githubusercontent.com/<YOUR_GITHUB_USERNAME>/<REPO>/main/data/latest.json`

For this account, replace `<YOUR_GITHUB_USERNAME>` with `iphoenk`.

## Local setup

```bash
pip install -r requirements.txt
python export_master.py
```

## Enhanced local collector

```bash
python fpl_daily_tasks.py current-gw
python fpl_daily_tasks.py health
python fpl_daily_tasks.py price-check
python fpl_daily_tasks.py price-predict --top 10
python fpl_daily_tasks.py team-value
python fpl_daily_tasks.py chip-state
python fpl_daily_tasks.py live-score
python fpl_daily_tasks.py reconcile
python fpl_daily_tasks.py snapshot
```

## GitHub Actions

`.github/workflows/fpl-engine.yml` runs hourly at minute `:20` UTC-clock cadence.

The FPL Master Monitor can run at `:30`, leaving a buffer for the collector.

### Important

GitHub Actions scheduled workflows can be delayed by GitHub. `data/latest.json` includes a timestamp, so the Master Monitor must always validate freshness rather than assume the scheduled run happened exactly on time.

## Security

No FPL username, password, OAuth token, session cookie, or private endpoint is required.

This collector uses public read-only endpoints only.

Never commit an authenticated FPL session cookie to this repository.
