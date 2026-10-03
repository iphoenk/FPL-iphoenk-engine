from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from src.engines.report_time_intelligence import validate_evidence


SOURCE_CLASSES = {
    "OFFICIAL",
    "RELIABLE_REPORT",
    "MULTIPLE_CREDIBLE_REPORTS",
    "RUMOR / UNVERIFIED",
    "MODEL_SIGNAL",
    "INFERENCE",
}


def normalize_material_news_item(item: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize one report-time item without granting it decision authority."""
    row = dict(item)
    source_class = str(row.get("source_class") or "INFERENCE").strip().upper()
    if source_class == "RUMOR":
        source_class = "RUMOR / UNVERIFIED"
    if source_class not in SOURCE_CLASSES:
        source_class = "INFERENCE"

    evidence_status = str(row.get("evidence_status") or "").strip()
    if source_class == "RUMOR / UNVERIFIED":
        evidence_status = "UNVERIFIED"

    return {
        "subject": row.get("subject") or "UNAVAILABLE",
        "headline": row.get("headline") or row.get("summary") or "UNAVAILABLE",
        "summary": row.get("summary") or row.get("headline") or "UNAVAILABLE",
        "source_class": source_class,
        "source_name": row.get("source_name") or "UNAVAILABLE",
        "published_or_observed_timestamp": (
            row.get("published_or_observed_timestamp")
            or row.get("observed_at")
            or row.get("published_at")
        ),
        "affected_player_team": row.get("affected_player_team") or "UNAVAILABLE",
        "evidence_status": evidence_status or "OBSERVED",
        "decision_relevance": row.get("decision_relevance") or "MONITOR",
        "audience": row.get("audience") or "OTHER_MATERIAL",
        "news_observation_is_model_update": False,
        "act_authority": False,
    }


def build_official_fpl_material_news(
    bootstrap: Mapping[str, Any],
    *,
    our_element_ids: Sequence[int],
    watchlist_element_ids: Sequence[int],
    report_timestamp: str,
    previous_report_timestamp: str | None = None,
) -> list[dict[str, Any]]:
    """Build supportable material availability news from Official FPL only.

    This deliberately does not infer journalist reports or rumors from absence,
    status codes, or model state. External report-time collectors can append
    items through normalize_material_news_item when such evidence is bound.
    """
    our_ids = {int(value) for value in our_element_ids if int(value) > 0}
    watch_ids = {int(value) for value in watchlist_element_ids if int(value) > 0}
    rows: list[dict[str, Any]] = []

    for raw in bootstrap.get("elements") or []:
        if not isinstance(raw, Mapping):
            continue
        try:
            element_id = int(raw.get("id") or 0)
        except (TypeError, ValueError):
            continue
        news = str(raw.get("news") or "").strip()
        if element_id <= 0 or not news:
            continue

        news_added = raw.get("news_added")
        new_since_previous: bool | str = True
        if previous_report_timestamp and news_added:
            try:
                news_dt = datetime.fromisoformat(str(news_added).replace("Z", "+00:00"))
                previous_dt = datetime.fromisoformat(
                    str(previous_report_timestamp).replace("Z", "+00:00")
                )
                if news_dt.tzinfo is not None and previous_dt.tzinfo is not None:
                    if news_dt <= previous_dt:
                        continue
                else:
                    new_since_previous = "UNVERIFIED_TIMESTAMP"
            except ValueError:
                new_since_previous = "UNVERIFIED_TIMESTAMP"
        elif previous_report_timestamp and not news_added:
            new_since_previous = "UNVERIFIED_TIMESTAMP"
        if element_id in our_ids:
            audience = "OUR15"
        elif element_id in watch_ids:
            audience = "WATCHLIST / TARGETS"
        else:
            # Avoid turning the full official feed into a noise dump.
            continue

        player = (
            raw.get("web_name")
            or raw.get("second_name")
            or raw.get("first_name")
            or f"element:{element_id}"
        )
        rows.append(
            normalize_material_news_item(
                {
                    "subject": player,
                    "headline": news,
                    "summary": news,
                    "source_class": "OFFICIAL",
                    "source_name": "Official FPL",
                    "published_or_observed_timestamp": (
                        news_added or report_timestamp
                    ),
                    "new_since_previous_deep": new_since_previous,
                    "affected_player_team": {
                        "element_id": element_id,
                        "team_id": raw.get("team"),
                    },
                    "evidence_status": "CONFIRMED_OFFICIAL_FPL_FEED",
                    "decision_relevance": "AVAILABILITY / MINUTES MONITOR",
                    "audience": audience,
                }
            )
        )
    return rows


def _subject_key(value: Any) -> str:
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


def build_report_time_material_news(
    evidence_payload: Mapping[str, Any] | None,
    bootstrap: Mapping[str, Any],
    *,
    our_element_ids: Sequence[int],
    watchlist_element_ids: Sequence[int],
    report_timestamp: str,
) -> list[dict[str, Any]]:
    """Surface already-bound report-time evidence without creating new authority.

    This consumes the existing report_time_evidence_v1 contract only. It never
    fetches the web, never mutates V6/DSS/model numbers, and ignores unrelated
    subjects so S04 does not become a generic news dump.
    """
    payload = dict(evidence_payload or {})
    if payload.get("contract") != "report_time_evidence_v1":
        return []

    try:
        now = datetime.fromisoformat(str(report_timestamp).replace("Z", "+00:00"))
    except ValueError:
        return []
    if now.tzinfo is None:
        return []
    validation = validate_evidence(
        payload,
        now=now.astimezone(timezone.utc),
    )

    our_ids = {int(value) for value in our_element_ids if int(value) > 0}
    watch_ids = {int(value) for value in watchlist_element_ids if int(value) > 0}
    player_audience: dict[str, str] = {}
    relevant_team_keys: set[str] = set()
    team_name_by_id = {
        int(row.get("id") or 0): str(row.get("name") or row.get("short_name") or "")
        for row in bootstrap.get("teams") or []
        if isinstance(row, Mapping) and int(row.get("id") or 0) > 0
    }
    for raw in bootstrap.get("elements") or []:
        if not isinstance(raw, Mapping):
            continue
        try:
            element_id = int(raw.get("id") or 0)
        except (TypeError, ValueError):
            continue
        audience = (
            "OUR15"
            if element_id in our_ids
            else "WATCHLIST / TARGETS"
            if element_id in watch_ids
            else None
        )
        if audience is None:
            continue
        for name in (
            raw.get("web_name"),
            raw.get("first_name"),
            raw.get("second_name"),
            " ".join(
                value
                for value in (
                    str(raw.get("first_name") or "").strip(),
                    str(raw.get("second_name") or "").strip(),
                )
                if value
            ),
        ):
            key = _subject_key(name)
            if key:
                player_audience[key] = audience
        try:
            team_id = int(raw.get("team") or 0)
        except (TypeError, ValueError):
            team_id = 0
        team_key = _subject_key(team_name_by_id.get(team_id))
        if team_key:
            relevant_team_keys.add(team_key)

    class_map = {
        "VERIFIED_NEWS": "OFFICIAL",
        "SECONDARY_AVAILABILITY": "RELIABLE_REPORT",
        "COMMUNITY_SIGNAL": "RUMOR / UNVERIFIED",
        "PUNDIT_CONSENSUS": "INFERENCE",
        "FIXTURE_STRATEGY_EXPERT": "INFERENCE",
        "MODEL_CHALLENGER": "INFERENCE",
    }
    material: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in validation.get("accepted") or []:
        if not isinstance(raw, Mapping) or raw.get("current") is not True:
            continue
        source_class_raw = str(raw.get("source_class") or "")
        source_class = class_map.get(source_class_raw)
        if source_class is None:
            continue

        subject = str(raw.get("subject") or "").strip()
        summary = str(raw.get("summary") or "").strip()
        subject_key = _subject_key(subject)
        audience = player_audience.get(subject_key)
        if audience is None and subject_key in relevant_team_keys:
            audience = "TEAM / TACTICAL"
        if audience is None:
            searchable = _subject_key(subject + " " + summary)
            matched_player = next(
                (
                    value
                    for key, value in player_audience.items()
                    if key and key in searchable
                ),
                None,
            )
            if matched_player is not None:
                audience = matched_player
            elif any(key and key in searchable for key in relevant_team_keys):
                audience = "TEAM / TACTICAL"
        if audience is None:
            continue

        source_id = str(raw.get("source_id") or "UNAVAILABLE")
        fingerprint = (source_id, subject_key, summary.casefold())
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        material.append(
            normalize_material_news_item(
                {
                    "subject": subject or "UNAVAILABLE",
                    "headline": summary or subject or "UNAVAILABLE",
                    "summary": summary or subject or "UNAVAILABLE",
                    "source_class": source_class,
                    "source_name": source_id,
                    "published_or_observed_timestamp": raw.get("observed_at"),
                    "affected_player_team": subject or "UNAVAILABLE",
                    "evidence_status": (
                        "UNVERIFIED"
                        if source_class == "RUMOR / UNVERIFIED"
                        else "CURRENT_REPORT_TIME_EVIDENCE"
                    ),
                    "decision_relevance": (
                        f"{raw.get('topic') or 'NEWS'} / {raw.get('stance') or 'MONITOR'}"
                    ),
                    "audience": audience,
                }
            )
        )
    return material
