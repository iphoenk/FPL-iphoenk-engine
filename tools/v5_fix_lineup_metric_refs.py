from pathlib import Path

path = Path("src/v5/decision/lineup_optimizer.py")
text = path.read_text(encoding="utf-8")
old1 = '_cached_metrics(row, gw, "player_score", lineup_cfg)["mean"]'
new1 = 'gw_projection(row, gw)["mean"]'
old2 = '_cached_metrics(row, gw, "bench_score", lineup_cfg)["score"]'
new2 = 'player_score(row, gw, "bench_score")'
for old, new in ((old1, new1), (old2, new2)):
    if text.count(old) != 1:
        raise SystemExit(f"expected one occurrence of {old!r}, found {text.count(old)}")
    text = text.replace(old, new, 1)
if "_cached_metrics(" in text:
    raise SystemExit("stale undefined _cached_metrics reference remains")
path.write_text(text, encoding="utf-8")
