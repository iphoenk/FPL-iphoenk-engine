from __future__ import annotations

from pathlib import Path
import re


path = Path("src/intelligence/understat_tactical.py")
text = path.read_text(encoding="utf-8")

old = "from difflib import SequenceMatcher\nfrom statistics import median\n"
new = "from difflib import SequenceMatcher\nfrom functools import lru_cache\nfrom statistics import median\n"
if text.count(old) != 1:
    raise SystemExit(f"unexpected import anchor count={text.count(old)}")
text = text.replace(old, new, 1)

norm_block = '''_TRANSLITERATION_TABLE = str.maketrans(
    {
        "Đ": "D", "đ": "d", "Ł": "L", "ł": "l", "Ø": "O", "ø": "o",
        "Ð": "D", "ð": "d", "Þ": "Th", "þ": "th", "Æ": "AE", "æ": "ae",
        "Œ": "OE", "œ": "oe",
    }
)
_TEAM_REPRESENTATION_ALIASES = {
    "man utd": "manchester united",
    "man united": "manchester united",
    "man city": "manchester city",
    "spurs": "tottenham",
    "tottenham hotspur": "tottenham",
    "wolves": "wolverhampton wanderers",
    "newcastle": "newcastle united",
    "west ham": "west ham united",
    "brighton": "brighton and hove albion",
    "hull city": "hull",
    "ipswich town": "ipswich",
    "coventry city": "coventry",
}


@lru_cache(maxsize=4096)
def _norm_text(value: str) -> str:
    text = html.unescape(value).translate(_TRANSLITERATION_TABLE)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()
    return _TEAM_REPRESENTATION_ALIASES.get(text, text)


def _norm(value: Any) -> str:
    return _norm_text(str(value or ""))


def _metric'''
text, count = re.subn(
    r"def _norm\(value: Any\) -> str:\n.*?\n\n\ndef _metric",
    norm_block,
    text,
    count=1,
    flags=re.S,
)
if count != 1:
    raise SystemExit(f"_norm replacement count={count}")

helper = '''@lru_cache(maxsize=4096)
def _identity_tokens(value: str) -> tuple[str, ...]:
    return tuple(token for token in value.split() if token)


@lru_cache(maxsize=4096)
def _identity_token_set(value: str) -> frozenset[str]:
    return frozenset(_identity_tokens(value))


def _identity_index(candidates: list[dict]) -> dict[str, dict]:
    by_team: dict[str, list[dict]] = {}
    by_name: dict[str, list[dict]] = {}
    by_token: dict[str, list[dict]] = {}
    for row in candidates:
        normalized_name = str(row.get("normalized_name") or "")
        tokens = _identity_tokens(normalized_name)
        row["_identity_tokens"] = tokens
        row["_identity_token_set"] = frozenset(tokens)
        if normalized_name:
            by_name.setdefault(normalized_name, []).append(row)
        for team in row.get("normalized_teams", []) or []:
            if team:
                by_team.setdefault(str(team), []).append(row)
        for token in tokens:
            by_token.setdefault(token, []).append(row)
    return {"by_team": by_team, "by_name": by_name, "by_token": by_token}


def _map_player'''
text, count = re.subn(
    r"def _map_player",
    helper,
    text,
    count=1,
)
if count != 1:
    raise SystemExit(f"identity helper insertion count={count}")

old_sig = "def _map_player(official: dict, candidates: list[dict], policy: dict) -> tuple[dict | None, float, str]:"
new_sig = "def _map_player(official: dict, candidates: list[dict], policy: dict, identity_index: dict | None = None) -> tuple[dict | None, float, str]:"
if text.count(old_sig) != 1:
    raise SystemExit(f"_map_player signature count={text.count(old_sig)}")
text = text.replace(old_sig, new_sig, 1)

nested = '''    def tokens(value: str) -> tuple[str, ...]:
        return tuple(token for token in value.split() if token)

    def token_set(value: str) -> frozenset[str]:
        return frozenset(tokens(value))

'''
replacement = '''    tokens = _identity_tokens
    token_set = _identity_token_set

'''
if text.count(nested) != 1:
    raise SystemExit(f"nested token helper count={text.count(nested)}")
text = text.replace(nested, replacement, 1)

old_team = '    team_candidates = [row for row in candidates if team and team in row.get("normalized_teams", [])]\n'
new_team = '    index = identity_index or _identity_index(candidates)\n    team_candidates = list((index.get("by_team") or {}).get(team, ())) if team else []\n'
if text.count(old_team) != 1:
    raise SystemExit(f"team candidate anchor count={text.count(old_team)}")
text = text.replace(old_team, new_team, 1)

old_near = '''    near = []
    for row in team_candidates:
        candidate_tokens = tokens(row.get("normalized_name") or "")
        if len(candidate_tokens) < 2 or not full_token_seq:
            continue
        best = [
            max(SequenceMatcher(None, source_token, official_token).ratio() for official_token in full_token_seq)
            for source_token in candidate_tokens
        ]
        exact_anchor = any(source_token in full_tokens for source_token in candidate_tokens)
        average = sum(best) / len(best)
        if exact_anchor and min(best) >= 0.80 and average >= 0.90:
            near.append((average, row))
'''
new_near = '''    near = []
    for row in team_candidates:
        candidate_tokens = row.get("_identity_tokens") or tokens(row.get("normalized_name") or "")
        if len(candidate_tokens) < 2 or not full_token_seq:
            continue
        exact_anchor = any(source_token in full_tokens for source_token in candidate_tokens)
        if not exact_anchor:
            continue
        best = [
            max(SequenceMatcher(None, source_token, official_token).ratio() for official_token in full_token_seq)
            for source_token in candidate_tokens
        ]
        average = sum(best) / len(best)
        if min(best) >= 0.80 and average >= 0.90:
            near.append((average, row))
'''
if text.count(old_near) != 1:
    raise SystemExit(f"near-token anchor count={text.count(old_near)}")
text = text.replace(old_near, new_near, 1)

text = text.replace(
    '            candidate_tokens = tokens(row.get("normalized_name") or "")\n            if len(candidate_tokens) == 1 and candidate_tokens[0] == first_token:\n',
    '            candidate_tokens = row.get("_identity_tokens") or tokens(row.get("normalized_name") or "")\n            if len(candidate_tokens) == 1 and candidate_tokens[0] == first_token:\n',
    1,
)
text = text.replace(
    '            candidate_tokens = token_set(row.get("normalized_name") or "")\n            if surname_anchor in candidate_tokens:\n',
    '            candidate_tokens = row.get("_identity_token_set") or token_set(row.get("normalized_name") or "")\n            if surname_anchor in candidate_tokens:\n',
    1,
)
text = text.replace(
    '        candidate_tokens = token_set(row.get("normalized_name") or "")\n        if not candidate_tokens:\n',
    '        candidate_tokens = row.get("_identity_token_set") or token_set(row.get("normalized_name") or "")\n        if not candidate_tokens:\n',
    1,
)

old_global_exact = '    global_exact = [row for row in candidates if row.get("normalized_name") in global_exact_names]\n'
new_global_exact = '''    global_exact = []
    for global_name in global_exact_names:
        global_exact.extend((index.get("by_name") or {}).get(global_name, ()))
'''
if text.count(old_global_exact) != 1:
    raise SystemExit(f"global exact anchor count={text.count(old_global_exact)}")
text = text.replace(old_global_exact, new_global_exact, 1)

old_global_struct = '''    global_structural = []
    if len(full_tokens) >= 2:
        for row in candidates:
            candidate_tokens = token_set(row.get("normalized_name") or "")
            if len(candidate_tokens) >= 2 and (
                candidate_tokens == full_tokens
                or candidate_tokens <= full_tokens
                or full_tokens <= candidate_tokens
            ):
                global_structural.append(row)
'''
new_global_struct = '''    global_structural = []
    if len(full_tokens) >= 2:
        structural_pool: dict[str, dict] = {}
        for token in full_tokens:
            for row in (index.get("by_token") or {}).get(token, ()):
                source_key = str(row.get("understat_player_id") or id(row))
                structural_pool[source_key] = row
        for row in structural_pool.values():
            candidate_tokens = row.get("_identity_token_set") or token_set(row.get("normalized_name") or "")
            if len(candidate_tokens) >= 2 and (
                candidate_tokens == full_tokens
                or candidate_tokens <= full_tokens
                or full_tokens <= candidate_tokens
            ):
                global_structural.append(row)
'''
if text.count(old_global_struct) != 1:
    raise SystemExit(f"global structural anchor count={text.count(old_global_struct)}")
text = text.replace(old_global_struct, new_global_struct, 1)

old_norm_start = '''    candidates = _understat_players(raw)
    mapped: dict[str, dict] = {}
'''
new_norm_start = '''    candidates = _understat_players(raw)
    identity_index = _identity_index(candidates)
    mapped: dict[str, dict] = {}
'''
if text.count(old_norm_start) != 1:
    raise SystemExit(f"normalizer candidate anchor count={text.count(old_norm_start)}")
text = text.replace(old_norm_start, new_norm_start, 1)

old_call = '        row, confidence, method = _map_player(official, candidates, policy)\n'
new_call = '        row, confidence, method = _map_player(official, candidates, policy, identity_index)\n'
if text.count(old_call) != 1:
    raise SystemExit(f"map call count={text.count(old_call)}")
text = text.replace(old_call, new_call, 1)

old_out = '''    out = {}
    for official in official_universe:
'''
new_out = '''    out = {}
    median_keys = ("xg", "xga", "deep", "deep_allowed", "ppda")
    medians_by_home = {
        home_state: {key: _league_median(teams, key, home_state) for key in median_keys}
        for home_state in (True, False)
    }
    for official in official_universe:
'''
if text.count(old_out) != 1:
    raise SystemExit(f"matchup output anchor count={text.count(old_out)}")
text = text.replace(old_out, new_out, 1)

old_med = '        med = {key: _league_median(teams, key, home) for key in ("xg", "xga", "deep", "deep_allowed", "ppda")}\n'
new_med = '        med = medians_by_home[home]\n'
if text.count(old_med) != 1:
    raise SystemExit(f"median anchor count={text.count(old_med)}")
text = text.replace(old_med, new_med, 1)

path.write_text(text, encoding="utf-8")
