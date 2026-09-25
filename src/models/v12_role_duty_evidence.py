from __future__ import annotations

"""Role and duty evidence with FACT > DERIVED > INFERRED precedence."""

from typing import Any, Mapping, Sequence

from src.rules import ELEMENT_TYPE_TO_POSITION


def _rank(value: Any) -> int | None:
    try:
        out = int(value)
    except (TypeError, ValueError):
        return None
    return out if out > 0 else None


def _text(value: Any) -> str | None:
    value = str(value or "").strip()
    return value or None


def _minutes(row: Mapping[str, Any]) -> float:
    raw = row.get("minutes")
    if raw is None:
        raw = row.get("minutes_played")
    try:
        out = float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, out)


def _match_sort(row: Mapping[str, Any]) -> tuple[int, str]:
    try:
        gw = int(row.get("gw") or 0)
    except (TypeError, ValueError):
        gw = 0
    return gw, str(row.get("match_id") or row.get("fixture") or "")


def _fact(
    name: str,
    value: Any,
    *,
    source: str,
    definition: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "value": value,
        "classification": "FACT",
        "source": source,
        "definition": definition,
    }


def _derived(
    name: str,
    value: Any,
    *,
    source: str,
    definition: str,
    confidence: str,
    sample_size: Any = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "value": value,
        "classification": "DERIVED",
        "source": source,
        "definition": definition,
        "confidence": confidence,
        "sample_size": sample_size,
    }


def _inferred_claim(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": str(raw.get("name") or "external_role_claim"),
        "value": raw.get("value"),
        "classification": "INFERRED",
        "source": raw.get("source") or "EXTERNAL_ANALYST",
        "timestamp": raw.get("timestamp"),
        "confidence": str(raw.get("confidence") or "LOW").upper(),
        "claim": raw.get("claim"),
        "authoritative_override_forbidden": True,
    }


def _official_duties(player: Mapping[str, Any]) -> dict[str, Any]:
    corner_rank = _rank(player.get("corners_and_indirect_freekicks_order"))
    direct_rank = _rank(player.get("direct_freekicks_order"))
    penalty_rank = _rank(player.get("penalties_order"))
    corner_text = _text(player.get("corners_and_indirect_freekicks_text"))
    direct_text = _text(player.get("direct_freekicks_text"))
    penalty_text = _text(player.get("penalties_text"))
    source = "OFFICIAL_FPL_BOOTSTRAP"

    return {
        "penalty_duty": _fact(
            "penalty_duty",
            {"order": penalty_rank, "text": penalty_text},
            source=source,
            definition="Official FPL penalty order/text; missing remains missing.",
        ),
        "corner_and_indirect_fk_duty": _fact(
            "corner_and_indirect_fk_duty",
            {"order": corner_rank, "text": corner_text},
            source=source,
            definition=(
                "Official FPL combined corners and indirect free-kicks order/text. "
                "Corner and indirect-FK shares are not separated when Official FPL does not separate them."
            ),
        ),
        "direct_fk_duty": _fact(
            "direct_fk_duty",
            {"order": direct_rank, "text": direct_text},
            source=source,
            definition="Official FPL direct free-kick order/text.",
        ),
    }


def _starts_and_subs(rows: Sequence[Mapping[str, Any]], last_n: int = 5) -> dict[str, Any]:
    played = [dict(row) for row in rows if _minutes(row) > 0.0]
    played.sort(key=_match_sort)
    recent = played[-last_n:]
    starts = [row for row in recent if bool(row.get("starter"))]
    starts_count = len(starts)
    sample = len(recent)
    candidate_probability = (
        (starts_count + 1.0) / (sample + 2.0) if sample >= 3 else None
    )
    if sample >= 5:
        confidence = "MODERATE"
    elif sample >= 3:
        confidence = "LOW"
    else:
        confidence = "NONE"

    starter_minutes = [_minutes(row) for row in starts]
    full = sum(value >= 80.0 for value in starter_minutes)
    subbed = sum(60.0 <= value < 80.0 for value in starter_minutes)
    early = sum(0.0 < value < 60.0 for value in starter_minutes)

    return {
        "starts_last_n": _derived(
            "starts_last_n",
            {
                "window": last_n,
                "played_appearances": sample,
                "starts": starts_count,
                "start_share": round(starts_count / sample, 6) if sample else None,
            },
            source="MATCH_LEVEL_OFFICIAL_HISTORY",
            definition="Starts among latest played appearances, excluding zero-minute non-appearances.",
            confidence=confidence,
            sample_size=sample,
        ),
        "sub_timing_pattern": _derived(
            "sub_timing_pattern",
            {
                "sample_starts": starts_count,
                "start_full_80_plus": full,
                "start_subbed_60_79": subbed,
                "early_sub_under_60": early,
                "mean_starter_minutes": (
                    round(sum(starter_minutes) / len(starter_minutes), 3)
                    if starter_minutes
                    else None
                ),
            },
            source="MATCH_LEVEL_OFFICIAL_HISTORY",
            definition="Observed starter-minute pattern; does not infer manager intent.",
            confidence=confidence,
            sample_size=starts_count,
        ),
        "candidate_role_start_probability": _derived(
            "candidate_role_start_probability",
            None if candidate_probability is None else round(candidate_probability, 6),
            source="LATEST_PLAYED_APPEARANCE_START_HISTORY",
            definition=(
                "Laplace-smoothed recent start share, exposed only as candidate P1.1 role evidence; "
                "not a new xMins owner."
            ),
            confidence=confidence,
            sample_size=sample,
        ),
    }


def _xmins_security(xmins: Mapping[str, Any] | None) -> dict[str, Any]:
    xmins = dict(xmins or {})
    if not xmins:
        return _derived(
            "xmins_security",
            None,
            source="P1.1",
            definition="Existing P1.1 minutes-security evidence.",
            confidence="NONE",
        )
    value = {
        "expected_minutes": xmins.get("expected_minutes"),
        "start_probability": xmins.get("start_probability"),
        "p_60_plus": xmins.get("p_60_plus"),
        "confidence": xmins.get("confidence"),
        "start_probability_interval": xmins.get("start_probability_interval"),
        "expected_minutes_interval": xmins.get("expected_minutes_interval"),
    }
    return _derived(
        "xmins_security",
        value,
        source="P1.1_V12_PLAYER_MINUTES",
        definition="Read-only consumption of existing P1.1 minutes authority.",
        confidence=str(xmins.get("confidence") or "LOW").upper(),
    )


def build_role_duty_evidence(
    player: Mapping[str, Any],
    *,
    match_rows: Sequence[Mapping[str, Any]] = (),
    observed_role: Mapping[str, Any] | None = None,
    xmins: Mapping[str, Any] | None = None,
    external_claims: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    try:
        element_type = int(player.get("element_type") or 0)
    except (TypeError, ValueError):
        element_type = 0
    nominal = ELEMENT_TYPE_TO_POSITION.get(element_type)
    facts = {
        "nominal_position": _fact(
            "nominal_position",
            nominal,
            source="OFFICIAL_FPL_BOOTSTRAP",
            definition="Official FPL registered position.",
        ),
        **_official_duties(player),
    }

    recent = _starts_and_subs(match_rows)
    observed = dict(observed_role or {})
    role_profile = observed.get("profile")
    actual_role = _derived(
        "actual_tactical_role",
        role_profile if role_profile and role_profile != "UNASSESSED" else None,
        source=observed.get("source") or "OBSERVED_TACTICAL_CONTEXT",
        definition=(
            "Observed/derived tactical-role profile. This is not an authoritative club-declared position."
        ),
        confidence=str(observed.get("confidence") or "NONE").upper(),
        sample_size=observed.get("sample_size") or observed.get("evidence_minutes"),
    )
    inferred = [
        _inferred_claim(raw)
        for raw in external_claims
        if isinstance(raw, Mapping)
    ]

    conflicts: list[dict[str, Any]] = []
    official_penalty_order = facts["penalty_duty"]["value"]["order"]
    for claim in inferred:
        name = str(claim.get("name") or "").lower()
        if "penalty" in name and official_penalty_order is not None:
            conflicts.append(
                {
                    "field": "penalty_duty",
                    "authoritative_fact": facts["penalty_duty"]["value"],
                    "external_claim": claim,
                    "resolution": "OFFICIAL_FACT_PRESERVED",
                }
            )

    return {
        "contract": "V12_ROLE_DUTY_EVIDENCE_V1",
        "facts": facts,
        "derived": {
            **recent,
            "actual_tactical_role": actual_role,
            "xmins_security": _xmins_security(xmins),
        },
        "inferred": inferred,
        "conflicts": conflicts,
        "candidate_p1_1_context": {
            "role_start_probability": (
                recent["candidate_role_start_probability"]["value"]
                if recent["candidate_role_start_probability"]["confidence"] in {"LOW", "MODERATE", "HIGH"}
                else None
            ),
            "source": "DERIVED_RECENT_START_HISTORY",
            "automatic_application": False,
        },
        "governance": {
            "precedence": ["FACT", "DERIVED", "INFERRED"],
            "external_claim_cannot_overwrite_fact": True,
            "official_set_piece_rank_is_fact": True,
            "actual_tactical_role_is_derived_not_fact": True,
            "candidate_role_start_probability_does_not_create_new_xmins_owner": True,
        },
    }
