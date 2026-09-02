from __future__ import annotations

import math
import re
import unicodedata
from difflib import SequenceMatcher
from statistics import median
from typing import Any

from src.utils import CONFIG, DATA, atomic_json, iso_now, read_json

POLICY_FILE = CONFIG / "intelligence" / "understat_tactical.json"
OUTFILE = DATA / "understat_tactical_v4.json"


def _policy() -> dict:
    return read_json(POLICY_FILE, {}) or {}


def _f(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        out = float(value)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError):
        return None


def _rows(value: Any) -> list[dict]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        return [row for row in value.values() if isinstance(row, dict)]
    return []


def _norm(value: Any) -> str:
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


def _metric(row: dict, *keys: str) -> float | None:
    for key in keys:
        if key in row:
            value = _f(row.get(key))
            if value is not None:
                return value
    return None


def _ppda(row: dict, key: str = "ppda") -> float | None:
    value = row.get(key)
    if isinstance(value, dict):
        att = _f(value.get("att"))
        defensive = _f(value.get("def"))
        if att is not None and defensive and defensive > 0:
            return att / defensive
    return _f(value)


def _observed(value: Any, source_field: str) -> dict:
    return {
        "value": value,
        "evidence_type": "SOURCE_OBSERVED" if value is not None else "UNKNOWN",
        "source_field": source_field,
    }


def _derived(value: Any, derivation: str, inputs: list[str]) -> dict:
    return {
        "value": value,
        "evidence_type": "DERIVED" if value is not None else "UNKNOWN",
        "derivation": derivation,
        "derivation_version": "understat-tactical-v1",
        "inputs": inputs,
    }


def _confidence(matches: int, policy: dict) -> tuple[str, float]:
    cfg = policy.get("sample_size") or {}
    mature = max(1, int(cfg.get("mature_matches_at_least") or 5))
    low = max(1, int(cfg.get("low_confidence_matches_below") or 3))
    if matches <= 0:
        return "INSUFFICIENT_EVIDENCE", 0.0
    if matches < low:
        return "LOW_SAMPLE", min(0.4, matches / mature)
    if matches < mature:
        return "DEVELOPING", min(0.75, matches / mature)
    return "MATURE", 1.0


def _history_team_rows(raw: dict) -> list[dict]:
    embedded = raw.get("embedded") or {}
    out = []
    for team in _rows(embedded.get("teamsData")):
        title = team.get("title") or team.get("team_title") or team.get("name")
        history = _rows(team.get("history"))
        if title and history:
            out.append({"understat_team_id": team.get("id"), "title": title, "history": history})
    return out


def _raw_window(rows: list[dict], name: str, policy: dict) -> dict:
    metrics = {
        "xg": [_metric(row, "xG", "xg") for row in rows],
        "xga": [_metric(row, "xGA", "xga") for row in rows],
        "deep": [_metric(row, "deep") for row in rows],
        "deep_allowed": [_metric(row, "deep_allowed", "deepAllowed") for row in rows],
        "ppda": [_ppda(row, "ppda") for row in rows],
        "ppda_allowed": [_ppda(row, "ppda_allowed") for row in rows],
        "goals": [_metric(row, "scored", "goals") for row in rows],
        "goals_conceded": [_metric(row, "missed", "goals_conceded") for row in rows],
        "npxg": [_metric(row, "npxG", "npxg") for row in rows],
        "npxga": [_metric(row, "npxGA", "npxga") for row in rows],
    }
    means = {}
    for key, values in metrics.items():
        clean = [value for value in values if value is not None]
        means[key] = (sum(clean) / len(clean)) if clean else None
    state, confidence = _confidence(len(rows), policy)
    return {
        "window": name,
        "matches": len(rows),
        "sample_state": state,
        "confidence": round(confidence, 4),
        "metrics_raw_per_match": means,
        "missingness": {key: sum(value is None for value in values) for key, values in metrics.items()},
    }


def _window_rows(history: list[dict], spec: str | int) -> list[dict]:
    if isinstance(spec, int):
        return history[-spec:]
    if spec == "HOME":
        return [row for row in history if str(row.get("h_a") or row.get("side") or "").lower() in {"h", "home"}]
    if spec == "AWAY":
        return [row for row in history if str(row.get("h_a") or row.get("side") or "").lower() in {"a", "away"}]
    return history


def _league_means(teams: dict[str, dict], window_name: str) -> dict[str, float | None]:
    keys = ("xg", "xga", "deep", "deep_allowed", "ppda", "ppda_allowed", "goals", "goals_conceded", "npxg", "npxga")
    out = {}
    for key in keys:
        values = []
        for team in teams.values():
            value = (((team.get("windows") or {}).get(window_name) or {}).get("metrics_raw_per_match") or {}).get(key)
            if value is not None:
                values.append(float(value))
        out[key] = sum(values) / len(values) if values else None
    return out


def _apply_shrinkage(teams: dict[str, dict], policy: dict) -> None:
    prior = max(1.0, float((policy.get("sample_size") or {}).get("small_sample_shrinkage_prior_matches") or 5))
    names = {name for team in teams.values() for name in (team.get("windows") or {})}
    for window_name in names:
        league = _league_means(teams, window_name)
        for team in teams.values():
            window = (team.get("windows") or {}).get(window_name)
            if not window:
                continue
            n = int(window.get("matches") or 0)
            adjusted = {}
            evidence = {}
            for key, raw in (window.get("metrics_raw_per_match") or {}).items():
                prior_value = league.get(key)
                value = None
                if raw is not None and prior_value is not None:
                    value = (float(raw) * n + float(prior_value) * prior) / (n + prior)
                elif raw is not None:
                    value = float(raw)
                adjusted[key] = round(value, 5) if value is not None else None
                if key in {"ppda", "ppda_allowed"}:
                    evidence[key] = _derived(
                        round(raw, 5) if raw is not None else None,
                        "mean_of_per_match_understat_ppda_att_div_def",
                        [f"history.{key}.att", f"history.{key}.def"],
                    )
                else:
                    source_key = {"xg": "xG", "xga": "xGA", "npxg": "npxG", "npxga": "npxGA"}.get(key, key)
                    evidence[key] = _observed(round(raw, 5) if raw is not None else None, f"teamsData.history.{source_key}")
            window["metrics_adjusted_per_match"] = adjusted
            window["metric_evidence"] = evidence
            window["shrinkage"] = {
                "applied": n < int((policy.get("sample_size") or {}).get("mature_matches_at_least") or 5),
                "prior_matches": prior,
                "prior": "league_window_mean",
                "derivation_version": "understat-tactical-v1",
            }
            window["league_mean"] = {key: round(value, 5) if value is not None else None for key, value in league.items()}


def normalize_team_evidence(raw: dict, policy: dict | None = None) -> dict[str, dict]:
    policy = policy or _policy()
    teams: dict[str, dict] = {}
    for team in _history_team_rows(raw):
        history = team["history"]
        windows = {}
        for count in policy.get("rolling_windows") or [1, 3, 5]:
            windows[f"last_{int(count)}"] = _raw_window(_window_rows(history, int(count)), f"last_{int(count)}", policy)
        windows["season_to_date"] = _raw_window(history, "season_to_date", policy)
        for venue in policy.get("venue_splits") or ["HOME", "AWAY"]:
            windows[str(venue).lower()] = _raw_window(_window_rows(history, str(venue)), str(venue).lower(), policy)
        teams[_norm(team["title"])] = {
            "understat_team_id": team.get("understat_team_id"),
            "team": team["title"],
            "history_matches": len(history),
            "windows": windows,
        }
    _apply_shrinkage(teams, policy)
    return teams


def _player_rows(raw: dict) -> list[dict]:
    return _rows((raw.get("embedded") or {}).get("playersData"))


def _team_titles(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if value:
        return [part.strip() for part in str(value).split(",") if part.strip()]
    return []


def _player_season(row: dict, team_total: dict[str, float]) -> dict:
    minutes = _metric(row, "time", "minutes")
    games = int(_metric(row, "games") or 0)
    xg = _metric(row, "xG", "xg")
    xa = _metric(row, "xA", "xa")
    xgc = _metric(row, "xGChain", "xgchain")
    xgb = _metric(row, "xGBuildup", "xgbuildup")
    def per90(value: float | None) -> float | None:
        return (value * 90.0 / minutes) if value is not None and minutes and minutes > 0 else None
    def share(value: float | None, key: str) -> float | None:
        total = team_total.get(key) or 0.0
        return value / total if value is not None and total > 0 else None
    metrics = {
        "xg": _observed(xg, "playersData.xG"),
        "xa": _observed(xa, "playersData.xA"),
        "xgchain": _observed(xgc, "playersData.xGChain"),
        "xgbuildup": _observed(xgb, "playersData.xGBuildup"),
        "shots": _observed(_metric(row, "shots"), "playersData.shots"),
        "key_passes": _observed(_metric(row, "key_passes", "keyPasses"), "playersData.key_passes"),
        "minutes": _observed(minutes, "playersData.time"),
        "games": _observed(games, "playersData.games"),
    }
    derived = {
        "xg_per90": _derived(per90(xg), "xG*90/minutes", ["xG", "minutes"]),
        "xa_per90": _derived(per90(xa), "xA*90/minutes", ["xA", "minutes"]),
        "xgchain_per90": _derived(per90(xgc), "xGChain*90/minutes", ["xGChain", "minutes"]),
        "xgbuildup_per90": _derived(per90(xgb), "xGBuildup*90/minutes", ["xGBuildup", "minutes"]),
        "team_xg_share": _derived(share(xg, "xg"), "player_xG/team_player_xG", ["player.xG", "team.players.xG"]),
        "team_xa_share": _derived(share(xa, "xa"), "player_xA/team_player_xA", ["player.xA", "team.players.xA"]),
        "team_chain_share": _derived(share(xgc, "xgchain"), "player_xGChain/team_player_xGChain", ["player.xGChain", "team.players.xGChain"]),
        "team_buildup_share": _derived(share(xgb, "xgbuildup"), "player_xGBuildup/team_player_xGBuildup", ["player.xGBuildup", "team.players.xGBuildup"]),
    }
    return {"metrics": metrics, "derived": derived, "matches": games, "minutes": minutes}


def _understat_players(raw: dict) -> list[dict]:
    rows = _player_rows(raw)
    totals: dict[str, dict[str, float]] = {}
    for row in rows:
        for title in _team_titles(row.get("team_title") or row.get("team")):
            key = _norm(title)
            total = totals.setdefault(key, {"xg": 0.0, "xa": 0.0, "xgchain": 0.0, "xgbuildup": 0.0})
            for metric, fields in {
                "xg": ("xG", "xg"), "xa": ("xA", "xa"), "xgchain": ("xGChain", "xgchain"), "xgbuildup": ("xGBuildup", "xgbuildup")
            }.items():
                total[metric] += _metric(row, *fields) or 0.0
    out = []
    for row in rows:
        titles = _team_titles(row.get("team_title") or row.get("team"))
        primary = _norm(titles[0]) if titles else ""
        out.append({
            "understat_player_id": row.get("id"),
            "name": row.get("player_name") or row.get("name"),
            "normalized_name": _norm(row.get("player_name") or row.get("name")),
            "teams": titles,
            "normalized_teams": [_norm(title) for title in titles],
            "position": row.get("position"),
            "season_to_date": _player_season(row, totals.get(primary, {})),
        })
    return out


def _map_player(official: dict, candidates: list[dict], policy: dict) -> tuple[dict | None, float, str]:
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


def normalize_player_evidence(raw: dict, official_universe: list[dict], policy: dict | None = None) -> tuple[dict[str, dict], list[dict]]:
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


def _window(team: dict | None, home: bool | None = None) -> dict:
    if not team:
        return {}
    windows = team.get("windows") or {}
    venue = windows.get("home" if home else "away") if home is not None else None
    if venue and int(venue.get("matches") or 0) >= 3:
        return venue
    return windows.get("last_5") or windows.get("season_to_date") or {}


def _league_median(teams: dict[str, dict], key: str, home: bool | None = None) -> float | None:
    values = []
    for team in teams.values():
        value = ((_window(team, home).get("metrics_adjusted_per_match") or {}).get(key))
        if value is not None:
            values.append(float(value))
    return median(values) if values else None


def _cmp(value: float | None, centre: float | None, higher_positive: bool = True) -> int | None:
    if value is None or centre is None:
        return None
    if abs(value - centre) < 1e-9:
        return 0
    positive = value > centre
    return 1 if positive == higher_positive else -1


def _dimension(signals: list[int | None], label: str) -> dict:
    present = [value for value in signals if value is not None]
    if len(present) < 2:
        return {"state": "INSUFFICIENT_EVIDENCE", "support": [], "label": label}
    score = sum(present)
    state = "POSITIVE" if score >= 2 else "NEGATIVE" if score <= -2 else "NEUTRAL"
    return {"state": state, "signal_balance": score, "signal_count": len(present), "label": label}


def build_matchups(teams: dict[str, dict], players: dict[str, dict], official_universe: list[dict], fixtures: list[dict], policy: dict | None = None) -> dict[str, dict]:
    policy = policy or _policy()
    team_names_by_id = {}
    for row in official_universe:
        if row.get("team_id") and row.get("team"):
            team_names_by_id[int(row["team_id"])] = row["team"]
    future_by_team: dict[int, list[dict]] = {}
    for fixture in fixtures or []:
        if fixture.get("finished"):
            continue
        for team_id in (fixture.get("team_h"), fixture.get("team_a")):
            if team_id:
                future_by_team.setdefault(int(team_id), []).append(fixture)
    for rows in future_by_team.values():
        rows.sort(key=lambda row: (row.get("event") or 999, row.get("kickoff_time") or ""))

    out = {}
    for official in official_universe:
        element = int(official.get("element_id") or official.get("element") or 0)
        team_id = int(official.get("team_id") or 0)
        fixture = (future_by_team.get(team_id) or [None])[0]
        own_name = official.get("team")
        if not fixture or not own_name:
            out[str(element)] = {"state": "INSUFFICIENT_EVIDENCE", "reason": "NO_NEXT_FIXTURE"}
            continue
        home = int(fixture.get("team_h") or 0) == team_id
        opponent_id = int(fixture.get("team_a") if home else fixture.get("team_h") or 0)
        opponent_name = team_names_by_id.get(opponent_id)
        own = teams.get(_norm(own_name))
        opponent = teams.get(_norm(opponent_name)) if opponent_name else None
        own_window = _window(own, home)
        opp_window = _window(opponent, not home)
        own_matches = int(own_window.get("matches") or 0)
        opp_matches = int(opp_window.get("matches") or 0)
        if not own or not opponent or min(own_matches, opp_matches) < 1:
            out[str(element)] = {
                "state": "INSUFFICIENT_EVIDENCE",
                "confidence": 0.0,
                "sample_size": {"own": own_matches, "opponent": opp_matches},
                "opponent_id": opponent_id,
                "opponent": opponent_name,
                "reason": "TEAM_EVIDENCE_INCOMPLETE",
            }
            continue
        own_m = own_window.get("metrics_adjusted_per_match") or {}
        opp_m = opp_window.get("metrics_adjusted_per_match") or {}
        med = {key: _league_median(teams, key, home) for key in ("xg", "xga", "deep", "deep_allowed", "ppda")}
        attacking = _dimension([
            _cmp(own_m.get("xg"), med["xg"], True),
            _cmp(opp_m.get("xga"), med["xga"], True),
        ], "own chance quality x opponent concession quality")
        creativity = _dimension([
            _cmp(own_m.get("deep"), med["deep"], True),
            _cmp(opp_m.get("deep_allowed"), med["deep_allowed"], True),
        ], "own deep entries x opponent deep entries allowed")
        finishing = _dimension([
            _cmp(own_m.get("npxg") or own_m.get("xg"), med["xg"], True),
            _cmp(opp_m.get("npxga") or opp_m.get("xga"), med["xga"], True),
        ], "non-penalty chance environment")
        clean_sheet = _dimension([
            _cmp(own_m.get("xga"), med["xga"], False),
            _cmp(opp_m.get("xg"), med["xg"], False),
        ], "own defensive chance suppression x opponent attack")
        # PPDA is deliberately contextual only. Low PPDA is never converted into
        # a positive player/FPL state on its own.
        press_cmp = _cmp(own_m.get("ppda"), med["ppda"], False)
        transition = {
            "state": "INSUFFICIENT_EVIDENCE",
            "label": "transition environment",
            "context": {"own_press_vs_league": press_cmp},
            "reason": "PPDA_ALONE_CANNOT_ESTABLISH_TRANSITION_VALUE",
        }
        goalkeeper = {
            "state": "INSUFFICIENT_EVIDENCE",
            "label": "goalkeeper environment",
            "reason": "SHOT_VOLUME_NOT_RELIABLY_PRESENT_IN_GOVERNED_TEAM_SNAPSHOT",
        }
        set_piece = {
            "state": "INSUFFICIENT_EVIDENCE",
            "label": "set-piece environment",
            "reason": "UNDERSTAT_TEAM_SET_PIECE_SPLIT_NOT_PRESENT_IN_GOVERNED_SNAPSHOT",
        }
        dimensions = {
            "attacking_environment": attacking,
            "creativity_environment": creativity,
            "finishing_environment": finishing,
            "transition_environment": transition,
            "clean_sheet_environment": clean_sheet,
            "goalkeeper_environment": goalkeeper,
            "set_piece_environment": set_piece,
        }
        available_states = [row["state"] for row in dimensions.values() if row.get("state") != "INSUFFICIENT_EVIDENCE"]
        positives = available_states.count("POSITIVE")
        negatives = available_states.count("NEGATIVE")
        if len(available_states) < 2:
            state = "INSUFFICIENT_EVIDENCE"
        elif positives >= 2 and positives > negatives:
            state = "POSITIVE"
        elif negatives >= 2 and negatives > positives:
            state = "NEGATIVE"
        else:
            state = "NEUTRAL"
        player = players.get(str(element)) or {}
        mapping_conf = float((player.get("mapping") or {}).get("confidence") or 0.0)
        own_conf = float(own_window.get("confidence") or 0.0)
        opp_conf = float(opp_window.get("confidence") or 0.0)
        confidence = min(own_conf, opp_conf) * (mapping_conf if mapping_conf else 0.7)
        support = [name for name, row in dimensions.items() if row.get("state") == "POSITIVE"]
        conflict = [name for name, row in dimensions.items() if row.get("state") == "NEGATIVE"]
        out[str(element)] = {
            "state": state,
            "confidence": round(confidence, 4),
            "freshness": "SOURCE_SNAPSHOT",
            "sample_size": {"own": own_matches, "opponent": opp_matches},
            "own_team_evidence": {"team": own_name, "window": own_window.get("window"), "metrics": own_m},
            "opponent_evidence": {"team_id": opponent_id, "team": opponent_name, "window": opp_window.get("window"), "metrics": opp_m},
            "player_role_interaction": {
                "fpl_position": official.get("position"),
                "understat_season": player.get("season_to_date"),
                "mapping": player.get("mapping"),
                "xmins_authority": "V4_PREDICTION_NOT_UNDERSTAT",
            },
            "supporting_signals": support,
            "conflicting_signals": conflict,
            "uncertainty": {
                "small_sample": min(own_matches, opp_matches) < int((policy.get("sample_size") or {}).get("mature_matches_at_least") or 5),
                "player_recent_form_missing": True,
                "game_state_adjustment": "INSUFFICIENT_EVIDENCE",
                "red_card_adjustment": "INSUFFICIENT_EVIDENCE",
            },
            "dimensions": dimensions,
            "provenance": {
                "source": "Understat",
                "team_evidence": "teamsData.history",
                "player_evidence": "playersData season aggregate",
                "derivation_version": "understat-tactical-v1",
            },
            "guardrails": {
                "ppda_direct_xpts_conversion": False,
                "single_metric_authority": False,
                "missing_evidence_penalty": False,
            },
        }
    return out


def build_understat_tactical(raw: dict, snapshot: dict, official_universe: list[dict], policy: dict | None = None) -> dict:
    policy = policy or _policy()
    teams = normalize_team_evidence(raw, policy)
    players, unresolved = normalize_player_evidence(raw, official_universe, policy)
    fixtures = ((snapshot.get("official") or {}).get("fixtures") or [])
    matchups = build_matchups(teams, players, official_universe, fixtures, policy)
    mapped = sum((row.get("mapping") or {}).get("state") == "RESOLVED" for row in players.values())
    source_absent = sum((row.get("mapping") or {}).get("state") == "SOURCE_ABSENT_CURRENT_SEASON" for row in players.values())
    classified = sum(
        (row.get("mapping") or {}).get("state") in {"RESOLVED", "SOURCE_ABSENT_CURRENT_SEASON", "UNRESOLVED"}
        for row in players.values()
    )
    official_team_count = len({int(row.get("team_id") or 0) for row in official_universe if int(row.get("team_id") or 0)})
    source_present = mapped + len(unresolved)
    source_present_coverage = mapped / max(1, source_present)
    usable_matchups = sum(row.get("state") != "INSUFFICIENT_EVIDENCE" for row in matchups.values())
    source_available = raw.get("source_availability") in {"AVAILABLE", "STALE_FALLBACK"} and bool(raw.get("schema_valid"))
    crosswalk_complete = classified == len(official_universe)
    team_mapping_complete = len(teams) == official_team_count
    source_present_complete = len(unresolved) == 0
    status = (
        "AVAILABLE"
        if source_available and crosswalk_complete and team_mapping_complete and source_present_complete
        else "PARTIAL" if source_available else "UNAVAILABLE"
    )
    out = {
        "schema_version": 1,
        "contract": "UNDERSTAT_TACTICAL_INTELLIGENCE_V1",
        "generated_at": iso_now(),
        "source": {
            "provider": "Understat",
            "availability": raw.get("source_availability"),
            "freshness": raw.get("freshness"),
            "fetched_at": raw.get("fetched_at"),
            "source_timestamp": raw.get("source_timestamp"),
            "latest_match_covered": _latest_match_covered(raw),
            "schema_valid": raw.get("schema_valid"),
            "schema_defects": raw.get("schema_defects") or [],
            "fallback": bool(raw.get("fallback")),
            "cache_age_minutes": raw.get("cache_age_minutes"),
            "request_count": raw.get("request_count"),
            "provenance": raw.get("provenance") or {},
        },
        "health": {
            "status": status,
            "optional_enrichment": True,
            "team_mapping_coverage": len(teams),
            "team_mapping_count": len(teams),
            "official_team_count": official_team_count,
            "team_mapping_ratio": round(len(teams) / max(1, official_team_count), 4),
            "official_universe_count": len(official_universe),
            "player_mapping_count": mapped,
            "player_mapping_coverage": round(mapped / max(1, len(official_universe)), 4),
            "player_crosswalk_classified_count": classified,
            "player_crosswalk_coverage": round(classified / max(1, len(official_universe)), 4),
            "source_present_official_count": source_present,
            "source_present_mapping_count": mapped,
            "source_present_mapping_coverage": round(source_present_coverage, 4),
            "source_absent_current_season_count": source_absent,
            "identity_unresolved_count": len(unresolved),
            "unresolved_mapping_count": len(unresolved),
            "tactical_matchup_usable_count": usable_matchups,
            "tactical_matchup_coverage": round(usable_matchups / max(1, len(official_universe)), 4),
            "fallback_state": "LAST_KNOWN_GOOD" if raw.get("fallback") else "NONE",
            "degradation_reason": raw.get("refresh_error") or raw.get("error"),
            "provenance_coherent": bool(raw.get("provenance")) if source_available else True,
        },
        "team_evidence": teams,
        "player_evidence": players,
        "unresolved_mappings": unresolved,
        "tactical_matchups": matchups,
        "guardrails": {
            "official_fpl_authority_preserved": True,
            "understat_dynamic_enrichment_only": True,
            "unknown_not_zero": True,
            "source_observed_vs_derived_explicit": True,
            "small_sample_shrinkage_explicit": True,
            "mw1_mw2_not_mature": True,
            "ppda_direct_xpts_conversion_forbidden": True,
            "direct_xpts_mutation": False,
            "direct_xmins_mutation": False,
            "no_per_player_network_calls": True,
            "full_official_universe_mapping_attempted": True,
            "full_official_universe_crosswalk_classified": crosswalk_complete,
            "source_present_player_mapping_complete": source_present_complete,
            "team_mapping_complete": team_mapping_complete,
            "source_absent_not_fabricated_as_direct_match": True,
            "player_specific_aliases": False,
            "global_fuzzy_identity_match": False,
            "intelligence_parity_not_decision_parity": True,
        },
    }
    return out


def _latest_match_covered(raw: dict) -> str | None:
    dates = _rows((raw.get("embedded") or {}).get("datesData"))
    stamps = [str(row.get("datetime") or row.get("date") or "") for row in dates if row.get("datetime") or row.get("date")]
    return max(stamps) if stamps else None


def materialize(raw: dict, snapshot: dict, official_universe: list[dict]) -> dict:
    out = build_understat_tactical(raw, snapshot, official_universe)
    atomic_json(OUTFILE, out)
    return out
