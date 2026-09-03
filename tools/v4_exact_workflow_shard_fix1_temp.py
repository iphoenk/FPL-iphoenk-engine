from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "src/engines/v4_full_universe_package_shard_merge.py"
text = path.read_text(encoding="utf-8")
old = '    indexes = sorted(int((row.get("search") or {}).get("outgoing_shard_index") or -1) for row in shards)\n'
new = '    indexes = sorted(int((row.get("search") or {}).get("outgoing_shard_index")) for row in shards)\n'
if text.count(old) != 1:
    raise RuntimeError("expected shard-index parser once")
path.write_text(text.replace(old, new), encoding="utf-8")
print("zero-valued shard index preserved")
