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
        "hull city": "hull",
        "ipswich town": "ipswich",
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
        official.get("first_name"),
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

    def tokens(value: str) -> tuple[str, ...]:
        return tuple(token for token in value.split() if token)

    def token_set(value: str) -> frozenset[str]:
        return frozenset(tokens(value))

    def position_buckets(value: object) -> set[str]:
        raw = str(value or "").upper()
        buckets: set[str] = set()
        for token in re.findall(r"[A-Z]+", raw):
            if token in {"G", "GK", "GOALKEEPER"}:
                buckets.add("GK")
            elif token in {"D", "DEF", "DEFENDER"}:
                buckets.add("DEF")
            elif token in {"M", "MID", "MIDFIELDER"}:
                buckets.add("MID")
            elif token in {"F", "FW", "FWD", "FORWARD", "STRIKER"}:
                buckets.add("FWD")
        return buckets

    official_positions = position_buckets(official.get("position"))

    def position_compatible(row: dict) -> bool:
        source_positions = position_buckets(row.get("position"))
        return not official_positions or not source_positions or bool(official_positions & source_positions)

    full_name = _norm(official.get("full_name") or official.get("name"))
    full_token_seq = tokens(full_name)
    full_tokens = frozenset(full_token_seq)
    first_name = _norm(official.get("first_name"))
    first_token = (tokens(first_name) or full_token_seq[:1] or ("",))[0]
    second_name = _norm(official.get("second_name"))
    surname_anchors = frozenset(
        token for token in tokens(second_name)
        if len(token) >= 4 and token not in {"filho", "junior"}
    )
    name_tokens = [token_set(name) for name in names if name]
    team_candidates = [
        row
        for row in candidates
        if team and team in row.get("normalized_teams", []) and position_compatible(row)
    ]

    exact = [row for row in team_candidates if row.get("normalized_name") in names]
    if len(exact) == 1:
        return exact[0], 1.0, "TEAM_AND_NORMALIZED_NAME_EXACT"

    # A source may publish a football mononym while Official FPL stores the
    # legal/full name. Only accept an exact first-token mononym when unique in
    # the same team and position bucket.
    mononym = []
    if first_token:
        for row in team_candidates:
            candidate_tokens = tokens(row.get("normalized_name") or "")
            if len(candidate_tokens) == 1 and candidate_tokens[0] == first_token:
                mononym.append(row)
    if len(mononym) == 1:
        return mononym[0], 0.995, "TEAM_SCOPED_MONONYM_EXACT"

    # Handle benign spelling/transliteration and truncated-family-name shapes
    # by aligning each source token to the closest Official full-name token.
    # Require a strong average, no weak token, and at least one exact anchor.
    near = []
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
    near.sort(key=lambda item: item[0], reverse=True)
    if near and (len(near) == 1 or near[0][0] - near[1][0] >= 0.03):
        return near[0][1], near[0][0], "TEAM_SCOPED_NEAR_TOKEN_IDENTITY"

    # When source and Official first names differ materially, a unique surname
    # token inside the same team/position is a deterministic identity anchor.
    surname = []
    if surname_anchors:
        for row in team_candidates:
            candidate_tokens = token_set(row.get("normalized_name") or "")
            if surname_anchors & candidate_tokens:
                surname.append(row)
    if len(surname) == 1:
        return surname[0], 0.99, "TEAM_SCOPED_UNIQUE_SURNAME_IDENTITY"

    # Generic structural identity bridge for multi-token subset/order changes.
    # Single-token variants are intentionally excluded here because mononym and
    # surname resolution above apply stricter semantics.
    structural = []
    for row in team_candidates:
        candidate_tokens = token_set(row.get("normalized_name") or "")
        if not candidate_tokens:
            continue
        same_tokens = any(variant and variant == candidate_tokens for variant in name_tokens)
        candidate_within_full = len(candidate_tokens) >= 2 and candidate_tokens <= full_tokens
        official_variant_within_candidate = any(
            len(variant) >= 2 and variant <= candidate_tokens for variant in name_tokens
        )
        if same_tokens or candidate_within_full or official_variant_within_candidate:
            structural.append(row)
    if len(structural) == 1:
        return structural[0], 0.985, "TEAM_SCOPED_STRUCTURAL_NAME_EXACT"

    # Deadline transfers can make Official current club newer than Understat's
    # represented club. Keep global fallback exact/structural only and position
    # compatible. Never use global fuzzy or player-specific aliases.
    global_exact = [
        row for row in candidates
        if position_compatible(row) and row.get("normalized_name") in names
    ]
    if len(global_exact) == 1:
        return global_exact[0], 0.97, "GLOBAL_NORMALIZED_NAME_EXACT_TEAM_TRANSITION"

    global_structural = []
    if len(full_tokens) >= 2:
        for row in candidates:
            if not position_compatible(row):
                continue
            candidate_tokens = token_set(row.get("normalized_name") or "")
            if len(candidate_tokens) >= 2 and (
                candidate_tokens == full_tokens
                or candidate_tokens <= full_tokens
                or full_tokens <= candidate_tokens
            ):
                global_structural.append(row)
    if len(global_structural) == 1:
        return global_structural[0], 0.965, "GLOBAL_STRUCTURAL_NAME_EXACT_TEAM_TRANSITION"

    # Last resort remains team-scoped fuzzy matching under governed thresholds.
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

normalizer = '''def normalize_player_evidence(raw: dict, official_universe: list[dict], policy: dict | None = None) -> tuple[dict[str, dict], list[dict]]:
    policy = policy or _policy()
    candidates = _understat_players(raw)
    mapped: dict[str, dict] = {}
    unresolved = []
    proposals = []
    for official in official_universe:
        element = int(official.get("element_id") or official.get("element") or 0)
        if not element:
            continue
        row, confidence, method = _map_player(official, candidates, policy)
        proposals.append({
            "official": official,
            "element": element,
            "row": row,
            "confidence": confidence,
            "method": method,
        })

    # Enforce a one-to-one cross-source identity. If two Official elements claim
    # the same Understat id, the more specific/higher-confidence proposal wins;
    # equal-confidence collisions are rejected rather than double-mapped.
    by_source: dict[str, list[int]] = {}
    for index, proposal in enumerate(proposals):
        row = proposal.get("row") or {}
        source_id = str(row.get("understat_player_id") or "")
        if source_id:
            by_source.setdefault(source_id, []).append(index)
    rejected: set[int] = set()
    for indexes in by_source.values():
        if len(indexes) <= 1:
            continue
        ranked = sorted(
            indexes,
            key=lambda index: float(proposals[index].get("confidence") or 0.0),
            reverse=True,
        )
        top = float(proposals[ranked[0]].get("confidence") or 0.0)
        second = float(proposals[ranked[1]].get("confidence") or 0.0)
        if top > second:
            rejected.update(ranked[1:])
        else:
            rejected.update(ranked)

    for index, proposal in enumerate(proposals):
        official = proposal["official"]
        element = proposal["element"]
        row = proposal.get("row")
        confidence = float(proposal.get("confidence") or 0.0)
        method = str(proposal.get("method") or "UNRESOLVED")
        if index in rejected:
            row = None
            confidence = 0.0
            method = "UNDERSTAT_IDENTITY_COLLISION"
        if not row:
            official_minutes = _f(official.get("minutes"))
            source_absent = official_minutes is not None and official_minutes <= 0 and method != "UNDERSTAT_IDENTITY_COLLISION"
            state = "SOURCE_ABSENT_CURRENT_SEASON" if source_absent else "UNRESOLVED"
            if not source_absent:
                unresolved.append({
                    "element": element,
                    "name": official.get("name"),
                    "team": official.get("team"),
                    "state": "IDENTITY_UNRESOLVED",
                    "official_minutes": official_minutes,
                    "method": method,
                })
            mapped[str(element)] = {
                "element": element,
                "official_name": official.get("name"),
                "official_team": official.get("team"),
                "mapping": {"state": state, "confidence": 0.0, "method": method},
                "season_to_date": None,
                "rolling_windows": {"last_1": None, "last_3": None, "last_5": None},
                "missingness": "UNDERSTAT_SOURCE_ABSENT_CURRENT_SEASON"
                if source_absent
                else "UNDERSTAT_PLAYER_IDENTITY_UNRESOLVED",
            }
            continue
        season = row.get("season_to_date") or {}
        matches = int(season.get("matches") or 0)
        sample_state, sample_confidence = _confidence(matches, policy)
        mapped[str(element)] = {
            "element": element,
            "official_name": official.get("name"),
            "official_team": official.get("team"),
            "understat_player_id": row.get("understat_player_id"),
            "understat_name": row.get("name"),
            "mapping": {"state": "RESOLVED", "confidence": round(confidence, 4), "method": method},
            "season_to_date": {
                **season,
                "sample_state": sample_state,
                "confidence": round(sample_confidence * confidence, 4),
            },
            "rolling_windows": {
                "last_1": {"state": "INSUFFICIENT_EVIDENCE", "reason": "PLAYER_MATCH_SERIES_NOT_SUPPLIED_BY_GOVERNED_SNAPSHOT"},
                "last_3": {"state": "INSUFFICIENT_EVIDENCE", "reason": "PLAYER_MATCH_SERIES_NOT_SUPPLIED_BY_GOVERNED_SNAPSHOT"},
                "last_5": {"state": "INSUFFICIENT_EVIDENCE", "reason": "PLAYER_MATCH_SERIES_NOT_SUPPLIED_BY_GOVERNED_SNAPSHOT"},
            },
            "missingness": None,
        }
    return mapped, unresolved


def _window'''
text, count = re.subn(
    r"def normalize_player_evidence\(raw: dict, official_universe: list\[dict\], policy: dict \| None = None\) -> tuple\[dict\[str, dict\], list\[dict\]\]:\n.*?\n\n\ndef _window",
    normalizer,
    text,
    count=1,
    flags=re.S,
)
if count != 1:
    raise SystemExit(f"normalize_player_evidence replacement count={count}")

path.write_text(text, encoding="utf-8")
