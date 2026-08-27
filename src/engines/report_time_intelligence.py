from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils import DATA, ROOT, atomic_json, read_json

REGISTRY_PATH = ROOT / "config" / "sources" / "report_time_registry.json"
SCHEMA_PATH = ROOT / "config" / "intelligence" / "report_time_evidence_schema.json"
EVIDENCE_PATH = DATA / "report_time_evidence.json"
OUTPUT_PATH = DATA / "report_time_intelligence.json"
CONTRACT = "report_time_evidence_v1"


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _subject_key(value: Any) -> str:
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


def _load_registry() -> dict[str, Any]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_registry(registry: dict[str, Any] | None = None) -> dict[str, Any]:
    registry = registry or _load_registry()
    schema = _load_schema()
    sources = registry.get("sources") or []
    ids = [str(row.get("id") or "") for row in sources]
    duplicates = sorted({source_id for source_id in ids if ids.count(source_id) > 1})
    allowed_classes = set(schema.get("allowed_source_classes") or [])
    invalid_classes = sorted(
        str(row.get("id")) for row in sources if str(row.get("class")) not in allowed_classes
    )
    onefpl = next((row for row in sources if row.get("id") == "onefpl"), {})
    ben = next((row for row in sources if row.get("id") == "ben_crellin"), {})
    reddit = next((row for row in sources if row.get("id") == "reddit_fantasypl"), {})
    ok = (
        not duplicates
        and not invalid_classes
        and registry.get("registry") == "REPORT_TIME_SOURCE_REGISTRY_V1"
        and bool((registry.get("policy") or {}).get("report_time_sources_never_mutate_dss"))
        and onefpl.get("class") == "MODEL_CHALLENGER"
        and onefpl.get("retrieval") == "REPORT_TIME_WEB"
        and ben.get("class") == "FIXTURE_STRATEGY_EXPERT"
        and ben.get("consensus_vote") is False
        and reddit.get("class") == "COMMUNITY_SIGNAL"
        and reddit.get("consensus_vote") is False
    )
    return {
        "registry": registry.get("registry"),
        "declared": len(sources),
        "enabled": sum(1 for row in sources if row.get("enabled") is True),
        "duplicates": duplicates,
        "invalid_classes": invalid_classes,
        "integrity_ok": bool(ok),
    }


def _source_map(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row.get("id")): row for row in registry.get("sources") or []}


def _current_signal(
    signal: dict[str, Any],
    source: dict[str, Any],
    registry: dict[str, Any],
    now: datetime,
) -> tuple[bool, float | None]:
    observed = _parse_dt(signal.get("observed_at"))
    if observed is None:
        return False, None
    age_hours = max(0.0, (now - observed).total_seconds() / 3600.0)
    class_name = str(source.get("class") or signal.get("source_class") or "")
    freshness = ((registry.get("consensus") or {}).get("freshness_hours") or {}).get(class_name)
    if freshness is None:
        return False, age_hours
    return age_hours <= float(freshness), age_hours


def validate_evidence(
    payload: dict[str, Any],
    *,
    registry: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    registry = registry or _load_registry()
    schema = _load_schema()
    now = now or datetime.now(timezone.utc)
    sources = _source_map(registry)
    required = set(schema.get("required_signal_fields") or [])
    allowed_stances = set(schema.get("allowed_stances") or [])
    allowed_classes = set(schema.get("allowed_source_classes") or [])
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for index, raw in enumerate(payload.get("signals") or []):
        if not isinstance(raw, dict):
            rejected.append({"index": index, "reason": "NOT_OBJECT"})
            continue
        missing = sorted(key for key in required if raw.get(key) in {None, ""})
        source_id = str(raw.get("source_id") or "")
        source = sources.get(source_id)
        if missing:
            rejected.append({"index": index, "source_id": source_id, "reason": "MISSING_FIELDS", "fields": missing})
            continue
        if source is None or source.get("enabled") is not True:
            rejected.append({"index": index, "source_id": source_id, "reason": "SOURCE_NOT_ENABLED"})
            continue
        if str(raw.get("source_class")) != str(source.get("class")):
            rejected.append({"index": index, "source_id": source_id, "reason": "SOURCE_CLASS_MISMATCH"})
            continue
        if str(raw.get("source_class")) not in allowed_classes:
            rejected.append({"index": index, "source_id": source_id, "reason": "INVALID_SOURCE_CLASS"})
            continue
        if str(raw.get("stance")) not in allowed_stances:
            rejected.append({"index": index, "source_id": source_id, "reason": "INVALID_STANCE"})
            continue
        current, age_hours = _current_signal(raw, source, registry, now)
        row = dict(raw)
        row["subject_key"] = _subject_key(row.get("subject"))
        row["current"] = current
        row["age_hours"] = round(age_hours, 2) if age_hours is not None else None
        row["consensus_eligible"] = bool(source.get("consensus_vote")) and current
        row["authority_ceiling"] = source.get("authority_ceiling")
        accepted.append(row)

    return {
        "contract": payload.get("contract"),
        "contract_ok": payload.get("contract") == CONTRACT,
        "accepted": accepted,
        "rejected": rejected,
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
    }


def _dss_subject_states(team: dict[str, Any], watchlist: dict[str, Any]) -> dict[str, dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    for row in team.get("team_value_ledger") or team.get("players") or []:
        name = row.get("name") or row.get("web_name")
        key = _subject_key(name)
        if key:
            states[key] = {"subject": name, "state": "OWNED", "element": row.get("element")}
    for rows in (watchlist.get("positions") or {}).values():
        for row in rows or []:
            name = row.get("name") or row.get("web_name")
            key = _subject_key(name)
            if key and key not in states:
                states[key] = {"subject": name, "state": "WATCHLIST", "element": row.get("element")}
    return states


def _alignment(stance: str, dss_state: str) -> str:
    if stance in {"BUY", "WATCH", "ROLE_POSITIVE"}:
        return "ALIGN" if dss_state in {"WATCHLIST", "OWNED"} else "DIVERGE"
    if stance == "HOLD":
        return "ALIGN" if dss_state == "OWNED" else "NEUTRAL"
    if stance in {"SELL", "ROLE_NEGATIVE", "INJURY_RISK"}:
        return "REVIEW_DIVERGENCE" if dss_state == "OWNED" else "NEUTRAL"
    return "NEUTRAL"


def build_pundit_consensus(
    accepted: list[dict[str, Any]],
    dss_states: dict[str, dict[str, Any]],
    registry: dict[str, Any],
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in accepted:
        if row.get("source_class") != "PUNDIT_CONSENSUS" or not row.get("consensus_eligible"):
            continue
        key = (str(row.get("topic") or ""), str(row.get("subject_key") or ""))
        if key[1]:
            groups[key].append(row)

    policy = registry.get("consensus") or {}
    minimum = int(policy.get("minimum_current_pundits") or 2)
    strong_ratio = float(policy.get("strong_consensus_ratio") or 0.75)
    simple_ratio = float(policy.get("simple_consensus_ratio") or 0.5)
    results: list[dict[str, Any]] = []
    for (topic, subject_key), rows in groups.items():
        providers = sorted({str(row.get("source_id")) for row in rows})
        if len(providers) < minimum:
            continue
        counts = Counter(str(row.get("stance")) for row in rows)
        top = counts.most_common()
        winner, votes = top[0]
        tied = len(top) > 1 and top[1][1] == votes
        ratio = votes / max(1, sum(counts.values()))
        if tied:
            strength = "SPLIT"
        elif ratio >= strong_ratio:
            strength = "STRONG"
        elif ratio > simple_ratio:
            strength = "CONSENSUS"
        else:
            strength = "SPLIT"
        dss = dss_states.get(subject_key, {"state": "OUTSIDE_DSS"})
        results.append({
            "topic": topic,
            "subject": rows[0].get("subject"),
            "subject_key": subject_key,
            "winner": winner if not tied else None,
            "strength": strength,
            "support_ratio": round(ratio, 3),
            "votes": dict(sorted(counts.items())),
            "providers": providers,
            "dss_state": dss.get("state"),
            "dss_element": dss.get("element"),
            "alignment_with_dss": _alignment(winner, str(dss.get("state"))) if not tied else "NEUTRAL",
            "advisory_only": True,
        })
    return sorted(results, key=lambda row: (row["alignment_with_dss"] != "DIVERGE", row["subject"] or ""))


def _class_signals(accepted: list[dict[str, Any]], class_name: str) -> list[dict[str, Any]]:
    return [
        {
            "source_id": row.get("source_id"),
            "topic": row.get("topic"),
            "subject": row.get("subject"),
            "stance": row.get("stance"),
            "summary": row.get("summary"),
            "observed_at": row.get("observed_at"),
            "source_url": row.get("source_url"),
            "current": row.get("current"),
            "authority_ceiling": row.get("authority_ceiling"),
        }
        for row in accepted
        if row.get("source_class") == class_name
    ]


def run(*, evidence_path: Path = EVIDENCE_PATH) -> dict[str, Any]:
    registry = _load_registry()
    registry_health = validate_registry(registry)
    team = read_json(DATA / "team.json", {})
    watchlist = read_json(DATA / "dss_watchlist.json", {})
    dss_states = _dss_subject_states(team, watchlist)

    if not evidence_path.exists():
        result = {
            "schema_version": 1,
            "model": "report_time_intelligence_v1",
            "status": "REFRESH_REQUIRED",
            "registry": registry_health,
            "web_refresh_required": True,
            "pundit_consensus": [],
            "fixture_strategy": [],
            "model_challenger": [],
            "community_signal": [],
            "verified_news": [],
            "policy": {
                "dss_is_not_mutated": True,
                "report_time_evidence_is_advisory": True,
                "community_requires_crosscheck": True,
            },
        }
        atomic_json(OUTPUT_PATH, result)
        return result

    payload = read_json(evidence_path, {})
    validation = validate_evidence(payload, registry=registry)
    accepted = validation["accepted"]
    result = {
        "schema_version": 1,
        "model": "report_time_intelligence_v1",
        "status": "READY" if validation["contract_ok"] else "INVALID_EVIDENCE_CONTRACT",
        "registry": registry_health,
        "evidence_contract": {
            "contract": validation["contract"],
            "contract_ok": validation["contract_ok"],
            "accepted": validation["accepted_count"],
            "rejected": validation["rejected_count"],
            "rejections": validation["rejected"],
        },
        "pundit_consensus": build_pundit_consensus(accepted, dss_states, registry),
        "fixture_strategy": _class_signals(accepted, "FIXTURE_STRATEGY_EXPERT"),
        "model_challenger": _class_signals(accepted, "MODEL_CHALLENGER"),
        "community_signal": _class_signals(accepted, "COMMUNITY_SIGNAL"),
        "verified_news": _class_signals(accepted, "VERIFIED_NEWS"),
        "policy": {
            "dss_is_not_mutated": True,
            "report_time_evidence_is_advisory": True,
            "pundit_consensus_is_compared_with_dss": True,
            "community_requires_crosscheck": True,
            "fixture_expert_does_not_vote_on_player_projection": True,
            "official_fpl_remains_native_authority": True,
        },
    }
    atomic_json(OUTPUT_PATH, result)
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
