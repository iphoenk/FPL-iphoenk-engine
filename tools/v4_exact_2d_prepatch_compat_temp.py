from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "src/engines/v4_full_universe_package_search_core.py"
text = path.read_text(encoding="utf-8")
old = "    need: Counter,\n"
new = "    need: dict[str, int],\n"
if text.count(old) != 1:
    raise RuntimeError(f"expected current exact-core need annotation once, found {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("2D staging anchor aligned to current exact-core signature")
