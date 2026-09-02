from __future__ import annotations

from pathlib import Path
import re


HELPER = Path("tools/temp_v4_understat_identity_patch.py")
text = HELPER.read_text(encoding="utf-8")


def reindent_literal(source: str, variable: str) -> str:
    pattern = rf"({re.escape(variable)} = ''')(.*?)(''')"
    match = re.search(pattern, source, flags=re.S)
    if not match:
        raise SystemExit(f"missing literal: {variable}")
    body = match.group(2)
    lines = body.splitlines()
    fixed = "\n".join(("    " + line if line else line) for line in lines)
    return source[: match.start(2)] + fixed + source[match.end(2) :]


for name in ("old_health", "new_health", "old_guard", "new_guard"):
    text = reindent_literal(text, name)

exec(compile(text, str(HELPER), "exec"), {"__name__": "__main__", "__file__": str(HELPER)})
