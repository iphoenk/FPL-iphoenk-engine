from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence


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
