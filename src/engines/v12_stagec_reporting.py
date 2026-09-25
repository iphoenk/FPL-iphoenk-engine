from __future__ import annotations

"""Visible Stage C subsections nested inside the canonical DEEP S04 section."""

from copy import deepcopy
from typing import Any, Mapping, Sequence

from src.models.v12_stagec_universe_scanner import load_config


SUBSECTIONS = (
    ("underlying_trajectory", "UNDERLYING TRAJECTORY"),
    ("positive_regression_watch", "POSITIVE REGRESSION WATCH"),
    ("negative_regression_watch", "NEGATIVE REGRESSION WATCH"),
    ("breakout_hidden_gems", "BREAKOUT / HIDDEN GEMS"),
    ("defcon_opportunities", "DEFCON OPPORTUNITIES"),
    ("role_minutes_changes", "ROLE / MINUTES CHANGES"),
    ("external_claim_challenge", "EXTERNAL CLAIM CHALLENGE"),
)


def _f(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _xgi90(row: Mapping[str, Any], window: str) -> float | None:
    return _f(
        ((((row.get("underlying") or {}).get(window) or {}).get("xgi") or {}).get("per90"))
    )


def _view(row: Mapping[str, Any]) -> dict[str, Any]:
    l3_returns = ((row.get("actual_returns") or {}).get("L3") or {})
    xmins = dict(row.get("xmins") or {})
    role = dict(row.get("role") or {})
    horizons = dict(row.get("fixture_horizon") or {})
    return {
        "element": row.get("element"),
        "player": row.get("name"),
        "position": row.get("position"),
        "actual_L3_GI": l3_returns.get("goal_involvements"),
        "L3_xGI90": _xgi90(row, "L3"),
        "L5_xGI90": _xgi90(row, "L5"),
        "season_xGI90": _xgi90(row, "SEASON"),
        "xmins": xmins.get("expected_minutes"),
        "p_start": xmins.get("p_start"),
        "role": role.get("actual"),
        "1GW": horizons.get("1"),
        "2GW": horizons.get("2"),
        "3GW": horizons.get("3"),
        "5GW": horizons.get("5"),
        "confidence": row.get("sample_confidence"),
        "signals": ",".join(str(x) for x in row.get("active_signals") or []),
        "why_flagged": "; ".join(str(x) for x in row.get("why_flagged") or []),
    }


def _signal(row: Mapping[str, Any], name: str) -> bool:
    return bool(((row.get("signals") or {}).get(name) or {}).get("active"))


def _limited(rows: Sequence[Mapping[str, Any]], limit: int) -> list[dict[str, Any]]:
    return [_view(row) for row in list(rows)[:limit]]


def _external_view(row: Mapping[str, Any]) -> dict[str, Any]:
    claim = dict(row.get("claim") or {})
    challenge = dict(row.get("model_challenge") or {})
    return {
        "source": claim.get("source"),
        "timestamp": claim.get("timestamp"),
        "element": claim.get("element"),
        "player": claim.get("player"),
        "claim": claim.get("stance"),
        "result": challenge.get("result"),
        "model_positive": ",".join(challenge.get("model_positive_signals") or []),
        "model_negative": ",".join(challenge.get("model_negative_signals") or []),
        "confidence": claim.get("confidence"),
        "raw_reference": claim.get("raw_reference"),
    }


def build_stagec_report_surface(
    *,
    scan: Mapping[str, Any],
    external_challenges: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = load_config()
    limit = max(1, int(cfg.get("material_render_limit_per_section") or 5))
    material = [
        dict(row)
        for row in scan.get("material_candidates") or []
        if isinstance(row, Mapping)
    ]
    positive = [row for row in material if _signal(row, "POSITIVE_REGRESSION")]
    negative = [row for row in material if _signal(row, "NEGATIVE_REGRESSION")]
    breakout = [
        row
        for row in material
        if _signal(row, "BREAKOUT") or bool(row.get("hidden_gem"))
    ]
    defcon = [row for row in material if _signal(row, "DEFCON_VALUE")]
    role_minutes = [
        row
        for row in material
        if any(
            _signal(row, key)
            for key in ("ROLE_GAIN", "ROLE_LOSS", "MINUTES_GAIN", "MINUTES_RISK")
        )
    ]
    external = [
        _external_view(row)
        for row in (external_challenges or {}).get("rows") or []
        if isinstance(row, Mapping)
    ][:limit]

    surface = {
        "underlying_trajectory": _limited(material, limit),
        "positive_regression_watch": _limited(positive, limit),
        "negative_regression_watch": _limited(negative, limit),
        "breakout_hidden_gems": _limited(breakout, limit),
        "defcon_opportunities": _limited(defcon, limit),
        "role_minutes_changes": _limited(role_minutes, limit),
        "external_claim_challenge": external,
    }
    return {
        "contract": "V12_STAGEC_DEEP_SUBSECTIONS_V1",
        "full_universe_count": scan.get("full_universe_count"),
        "material_candidate_count": scan.get("material_candidate_count"),
        "render_limit_per_section": limit,
        "subsections": surface,
        "rendered_row_count": sum(len(rows) for rows in surface.values()),
        "external_state": (external_challenges or {}).get("state", "NO_EXTERNAL_DATA"),
        "governance": {
            "nested_under_canonical_S04": True,
            "top_level_deep_section_catalog_changed": False,
            "full_universe_processed_only_material_rendered": True,
            "internal_candidate_ranking_not_final_decision": True,
            "external_opinion_not_ensembled": True,
        },
    }


def attach_stagec_to_deep_report(
    report: Mapping[str, Any],
    surface: Mapping[str, Any] | None,
    *,
    enabled: bool,
) -> dict[str, Any]:
    """Feature-off is structurally identical; enabled nests Stage C under S04."""
    if not enabled or not surface:
        return report if isinstance(report, dict) else dict(report)
    out = deepcopy(dict(report))
    target = next(
        (
            row
            for row in out.get("sections") or []
            if str(row.get("section_id") or "").upper() == "S04"
        ),
        None,
    )
    if target is None:
        raise ValueError("canonical DEEP S04 is required for Stage C nesting")
    content = dict(target.get("content") or {})
    content["stagec_universe_intelligence"] = deepcopy(dict(surface))
    target["content"] = content
    out["stagec_enabled"] = True
    return out


def _display(value: Any) -> str:
    if value is None or value == "":
        return "UNAVAILABLE"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def render_stagec_deep_lines(surface: Mapping[str, Any] | None) -> list[str]:
    payload = dict(surface or {})
    subsections = dict(payload.get("subsections") or {})
    lines = [
        "### STAGE C — UNIVERSE-WIDE ANALYTICS",
        (
            "Coverage: "
            f"{payload.get('full_universe_count', 'UNAVAILABLE')} players scanned | "
            f"material {payload.get('material_candidate_count', 'UNAVAILABLE')} | "
            f"render cap {payload.get('render_limit_per_section', 'UNAVAILABLE')}/subsection"
        ),
    ]
    for key, label in SUBSECTIONS:
        rows = [
            dict(row)
            for row in subsections.get(key) or []
            if isinstance(row, Mapping)
        ]
        lines.append(f"#### {label}")
        if not rows:
            lines.append(
                "NO MATERIAL CANDIDATES"
                if key != "external_claim_challenge"
                else "NO EXTERNAL DATA"
            )
            continue
        for row in rows:
            if key == "external_claim_challenge":
                lines.append(
                    "- "
                    f"{_display(row.get('player') or row.get('element'))} | "
                    f"{_display(row.get('source'))} {_display(row.get('claim'))} → "
                    f"{_display(row.get('result'))} | "
                    f"MODEL+={_display(row.get('model_positive'))} | "
                    f"MODEL-={_display(row.get('model_negative'))}"
                )
                continue
            lines.append(
                "- "
                f"{_display(row.get('player') or row.get('element'))} "
                f"({_display(row.get('position'))}) | "
                f"GI L3={_display(row.get('actual_L3_GI'))} | "
                f"xGI90 L3/L5/S={_display(row.get('L3_xGI90'))}/"
                f"{_display(row.get('L5_xGI90'))}/"
                f"{_display(row.get('season_xGI90'))} | "
                f"xMins={_display(row.get('xmins'))} "
                f"Pstart={_display(row.get('p_start'))} | "
                f"Role={_display(row.get('role'))} | "
                f"1/2/3/5GW={_display(row.get('1GW'))}/"
                f"{_display(row.get('2GW'))}/"
                f"{_display(row.get('3GW'))}/"
                f"{_display(row.get('5GW'))} | "
                f"Conf={_display(row.get('confidence'))} | "
                f"{_display(row.get('signals'))}"
            )
            if row.get("why_flagged"):
                lines.append("  Why: " + str(row.get("why_flagged")))
    return lines
