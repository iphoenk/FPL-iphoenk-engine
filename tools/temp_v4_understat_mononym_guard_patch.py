from __future__ import annotations

from pathlib import Path


path = Path("src/intelligence/understat_tactical.py")
text = path.read_text(encoding="utf-8")

old_names = '''        official.get("web_name"),
        official.get("first_name"),
        official.get("second_name"),
'''
new_names = '''        official.get("web_name"),
        official.get("second_name"),
'''
if text.count(old_names) != 1:
    raise SystemExit(f"expected one first-name raw identity slot, got {text.count(old_names)}")
text = text.replace(old_names, new_names, 1)

old_mononym = "    if first_token and official_minutes > 0:\n"
new_mononym = "    if first_token and official_minutes > 0 and web_name == first_token:\n"
if text.count(old_mononym) != 1:
    raise SystemExit(f"expected one mononym guard, got {text.count(old_mononym)}")
text = text.replace(old_mononym, new_mononym, 1)

path.write_text(text, encoding="utf-8")
