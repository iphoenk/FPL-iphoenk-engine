from __future__ import annotations

from pathlib import Path


path = Path("src/intelligence/understat_tactical.py")
text = path.read_text(encoding="utf-8")

# first_name is useful for the deliberately narrow team-scoped mononym path,
# but it must never participate as a general exact/fuzzy/structural identity
# alias. Otherwise unrelated same-first-name players can claim one source row.
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

# Preserve the governed observed-player mononym rule. Positive Official minutes
# are the safety condition; do not require web_name == first_name because real
# source mononyms can coexist with abbreviated/compound Official web names.
mononym_guard = "    if first_token and official_minutes > 0:\n"
if text.count(mononym_guard) != 1:
    raise SystemExit(f"expected one observed-player mononym guard, got {text.count(mononym_guard)}")

path.write_text(text, encoding="utf-8")
