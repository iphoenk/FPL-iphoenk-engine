from __future__ import annotations

from pathlib import Path
import re


path = Path("src/intelligence/understat_tactical.py")
text = path.read_text(encoding="utf-8")

norm = '''def _norm(value: Any) -> str:
    text = str(value or "").translate(
        str.maketrans(
            {
                "Đ": "D", "đ": "d", "Ł": "L", "ł": "l", "Ø": "O", "ø": "o",
                "Ð": "D", "ð": "d", "Þ": "Th", "þ": "th", "Æ": "AE", "æ": "ae",
                "Œ": "OE", "œ": "oe",
            }
        )
    )
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()
    aliases = {
        "man utd": "manchester united",
        "man united": "manchester united",
        "man city": "manchester city",
        "spurs": "tottenham",
        "tottenham hotspur": "tottenham",
        "wolves": "wolverhampton wanderers",
        "newcastle": "newcastle united",
        "west ham": "west ham united",
        "brighton": "brighton and hove albion",
    }
    return aliases.get(text, text)


def _metric'''
text, count = re.subn(r"def _norm\(value: Any\) -> str:\n.*?\n\n\ndef _metric", norm, text, count=1, flags=re.S)
if count != 1:
    raise SystemExit(f"_norm replacement count={count}")

mapper = '''def _map_player(official: dict, candidates: list[dict], policy: dict) -> tuple[dict | None, float, str]:
    team = _norm(official.get("team") or official.get("club"))
    raw_names = [
        official.get("name"),
        official.get("full_name"),
        official.get("web_name"),
        official.get("second_name"),
        *((official.get("name_variants") or [])),
    ]
    names = []
    seen = set()
    for value in raw_names:
        normalized = _norm(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            names.append(normalized)

    def token_set(value: str) -> frozenset[str]:
        return frozenset(token for token in value.split() if token)

    name_tokens = [token_set(name) for name in names if name]
    full_name = _norm(official.get("full_name") or official.get("name"))
    full_tokens = token_set(full_name)
    team_candidates = [row for row in candidates if team and team in row.get("normalized_teams", [])]

    exact = [row for row in team_candidates if row.get("normalized_name") in names]
    if len(exact) == 1:
        return exact[0], 1.0, "TEAM_AND_NORMALIZED_NAME_EXACT"

    # Generic structural identity bridge. This handles source names that omit
    # middle/family names, surname-only Official web names, and token order
    # differences. It is team-scoped and must resolve to exactly one candidate.
    structural = []
    for row in team_candidates:
        candidate_name = row.get("normalized_name") or ""
        candidate_tokens = token_set(candidate_name)
        if not candidate_tokens:
            continue
        same_tokens = any(tokens and tokens == candidate_tokens for tokens in name_tokens)
        candidate_within_full = len(candidate_tokens) >= 2 and candidate_tokens <= full_tokens
        official_variant_within_candidate = any(
            tokens and tokens <= candidate_tokens for tokens in name_tokens
        )
        if same_tokens or candidate_within_full or official_variant_within_candidate:
            structural.append(row)
    if len(structural) == 1:
        return structural[0], 0.995, "TEAM_SCOPED_STRUCTURAL_NAME_EXACT"

    # Deadline transfers can make Official current club newer than Understat's
    # represented club. Keep this global fallback exact/structural only. Never
    # perform global fuzzy matching and never add player-specific aliases.
    global_exact = [row for row in candidates if row.get("normalized_name") in names]
    if len(global_exact) == 1:
        return global_exact[0], 0.97, "GLOBAL_NORMALIZED_NAME_EXACT_TEAM_TRANSITION"

    global_structural = []
    if len(full_tokens) >= 2:
        for row in candidates:
            candidate_tokens = token_set(row.get("normalized_name") or "")
            if len(candidate_tokens) >= 2 and (
                candidate_tokens == full_tokens
                or candidate_tokens <= full_tokens
                or full_tokens <= candidate_tokens
            ):
                global_structural.append(row)
    if len(global_structural) == 1:
        return global_structural[0], 0.965, "GLOBAL_STRUCTURAL_NAME_EXACT_TEAM_TRANSITION"

    scored = sorted(
        (
            (
                max(
                    (SequenceMatcher(None, name, row.get("normalized_name") or "").ratio() for name in names),
                    default=0.0,
                ),
                row,
            )
            for row in team_candidates
        ),
        key=lambda item: item[0], reverse=True,
    )
    minimum = float((policy.get("identity") or {}).get("fuzzy_minimum_confidence") or 0.94)
    ambiguity = float((policy.get("identity") or {}).get("ambiguity_margin") or 0.03)
    if scored and scored[0][0] >= minimum and (len(scored) == 1 or scored[0][0] - scored[1][0] >= ambiguity):
        return scored[0][1], scored[0][0], "TEAM_SCOPED_FUZZY_NAME"
    return None, 0.0, "UNRESOLVED"


def normalize_player_evidence'''
text, count = re.subn(
    r"def _map_player\(official: dict, candidates: list\[dict\], policy: dict\) -> tuple\[dict \| None, float, str\]:\n.*?\n\n\ndef normalize_player_evidence",
    mapper,
    text,
    count=1,
    flags=re.S,
)
if count != 1:
    raise SystemExit(f"_map_player replacement count={count}")

path.write_text(text, encoding="utf-8")
