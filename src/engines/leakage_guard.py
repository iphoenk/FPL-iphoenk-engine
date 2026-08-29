from __future__ import annotations

from src.utils import parse_dt

FORBIDDEN_SAME_GW_FIELDS = {
    "xP", "ep_this", "event_points", "total_points", "bonus", "bps"
}


def availability_before_deadline(available_at: str | None, target_deadline: str | None) -> bool:
    """Canonical fail-closed predictive timing gate."""
    av = parse_dt(available_at)
    dl = parse_dt(target_deadline)
    return bool(av and dl and av <= dl)


def feature_is_eligible(feature_name: str, available_at: str | None, target_deadline: str | None, source_data_class: str | None):
    if feature_name in FORBIDDEN_SAME_GW_FIELDS and source_data_class in {"post_match_or_post_gw", "post_gw"}:
        return False, "post-event field blocked for same-GW pre-deadline prediction"
    if not availability_before_deadline(available_at, target_deadline):
        return False, "feature availability is missing, invalid, or after target deadline"
    return True, "eligible"


def filter_features(row: dict, available_at: str | None, target_deadline: str | None, source_data_class: str | None):
    clean = {}
    blocked = {}
    for key, value in row.items():
        ok, reason = feature_is_eligible(key, available_at, target_deadline, source_data_class)
        if ok:
            clean[key] = value
        else:
            blocked[key] = {"value": value, "reason": reason}
    return clean, blocked
