from __future__ import annotations

"""Canonical, responsive S06 pitch presentation.

This module is deliberately presentation-only. It accepts already selected
canonical XI/bench data and never chooses players or recomputes points.
"""

from html import escape
from typing import Any, Mapping, Sequence


def _name(value: Any) -> str:
    if isinstance(value, Mapping):
        return str(value.get("name") or value.get("player") or "UNAVAILABLE")
    return str(value or "UNAVAILABLE")


def _identity(value: Any) -> str:
    if isinstance(value, Mapping):
        return str(value.get("element") or value.get("element_id") or "")
    return str(value or "")


def render_s06_formation_frontier(content: Mapping[str, Any]) -> str:
    """Expose every already-calculated canonical formation (no new analytics)."""
    rows = [
        dict(row) for row in content.get("formation_comparison") or []
        if isinstance(row, Mapping)
        and isinstance(row.get("expected_fpl_points_with_captain_vice"), (int, float))
    ]
    rows.sort(key=lambda row: row["expected_fpl_points_with_captain_vice"], reverse=True)
    if not rows:
        return '<p>Formation comparison: UNAVAILABLE (no canonical P1.7 routes)</p>'
    best = float(rows[0]["expected_fpl_points_with_captain_vice"])
    body = "".join(
        '<tr><td>%s</td><td>%.3f</td><td>%+.3f</td></tr>' % (
            escape(str(row.get("formation") or "UNAVAILABLE")),
            float(row["expected_fpl_points_with_captain_vice"]),
            float(row["expected_fpl_points_with_captain_vice"]) - best,
        ) for row in rows
    )
    observed = {str(row.get("formation")) for row in rows}
    absent = [name for name in ("3-4-3", "3-5-2", "4-3-3", "4-4-2", "4-5-1", "5-2-3", "5-3-2", "5-4-1") if name not in observed]
    note = "Missing in canonical CURRENT15: " + escape(", ".join(absent)) if absent else ""
    return (
        '<div style="background:#10252b;color:#fff;border-radius:12px;padding:10px;margin-top:8px">'
        '<strong>All CURRENT15 formation winners (exact P1.7)</strong>'
        '<table style="width:100%%"><thead><tr><th>Formation</th><th>XI+C/VC xPts</th>'
        '<th>Gap</th></tr></thead><tbody>%s</tbody></table><p>%s</p>'
        '<p>DCL keep / DCL to Barry / DCL to Gonzalo require separate '
        'legality, prices, transfer hits, and canonical 500K Monte Carlo. '
        'Not yet simulated here.</p></div>' % (body, note)
    )


def render_s06_pitch(content: Mapping[str, Any]) -> str:
    """Return an accessible, mobile-first pitch and separate bench card."""
    xi = [row for row in content.get("starting_xi") or [] if isinstance(row, Mapping)]
    grouped = {position: [] for position in ("FWD", "MID", "DEF", "GK")}
    for row in xi:
        position = str(row.get("position") or row.get("pos") or "").upper()
        if position in grouped:
            grouped[position].append(row)

    captain = content.get("captain") or {}
    vice = content.get("vice_captain") or content.get("vice") or {}
    captain_id = _identity(captain)
    vice_id = _identity(vice)
    captain_name = _name(captain) if captain else ""
    vice_name = _name(vice) if vice else ""

    def token(row: Mapping[str, Any]) -> str:
        player_name = _name(row)
        identity = _identity(row)
        badge = ""
        if (identity and identity == captain_id) or (not identity and player_name == captain_name):
            badge = '<span class="s06-badge">C</span>'
        elif (identity and identity == vice_id) or (not identity and player_name == vice_name):
            badge = '<span class="s06-badge">VC</span>'
        points = row.get("xpts") or row.get("projection_1gw")
        point_text = f"<small>{escape(str(points))} xPts</small>" if points is not None else ""
        return (
            '<div class="s06-token" data-player="%s" data-position="%s">'
            '<span class="s06-circle">%s</span><span class="s06-nameplate">%s%s%s</span></div>'
            % (
                escape(identity or player_name),
                escape(str(row.get("position") or row.get("pos") or "UNAVAILABLE")),
                escape(player_name[:1] or "?"),
                escape(player_name),
                badge,
                point_text,
            )
        )

    layers = []
    for position in ("FWD", "MID", "DEF", "GK"):
        players = grouped[position]
        layer = "".join(token(row) for row in players) or '<span class="s06-missing">UNAVAILABLE</span>'
        layers.append(f'<div class="s06-line s06-{position.lower()}">{layer}</div>')

    bench = content.get("bench") or {}
    if not isinstance(bench, Mapping):
        bench = {}
    bench_gk = bench.get("bench_gk") or bench.get("gk") or bench.get("goalkeeper")
    order = bench.get("outfield_autosub_priority") or bench.get("order") or bench.get("outfield") or []
    if not isinstance(order, Sequence) or isinstance(order, (str, bytes)):
        order = []
    bench_values = [bench_gk, *list(order)[:3]]
    while len(bench_values) < 4:
        bench_values.append(None)
    bench_rows = "".join(
        '<div class="s06-bench-slot"><strong>%s</strong><span>%s</span></div>'
        % ("GK" if index == 0 else f"{index}", escape(_name(value)))
        for index, value in enumerate(bench_values, 0)
    )
    formation = escape(str(content.get("formation") or "UNAVAILABLE"))
    base = escape(str(content.get("xi_base_xpts") or "UNAVAILABLE"))
    adjusted = escape(str(content.get("captain_adjusted_xpts") or "UNAVAILABLE"))
    style = (
        '<style>'
        '.s06-dashboard{box-sizing:border-box;width:100%;max-width:430px;margin:10px auto;color:#eef8f0;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;line-height:1.2}'
        '.s06-pitch{box-sizing:border-box;padding:10px;border-radius:16px;background:#063d29;box-shadow:0 8px 20px rgba(0,0,0,.24);overflow:hidden}'
        '.s06-pitch-header{display:flex;flex-wrap:wrap;justify-content:space-between;gap:4px 10px;padding:2px 4px 9px;font-size:clamp(11px,3.1vw,14px)}'
        '.s06-pitch-header span{color:#bfe6ca;font-size:clamp(10px,2.7vw,12px)}'
        '.s06-field-markings{position:relative;display:flex;flex-direction:column;justify-content:space-around;gap:4px;min-height:350px;padding:18px 5px;border:2px solid rgba(255,255,255,.78);border-radius:10px;background:linear-gradient(90deg,rgba(255,255,255,.035) 0 12%,transparent 12% 25%,rgba(255,255,255,.035) 25% 37%,transparent 37% 50%,rgba(255,255,255,.035) 50% 62%,transparent 62% 75%,rgba(255,255,255,.035) 75% 87%,transparent 87%);overflow:hidden}'
        '.s06-field-markings:before{content:"";position:absolute;inset:50% 0 auto;border-top:1px solid rgba(255,255,255,.55)}'
        '.s06-field-markings:after{content:"";position:absolute;left:50%;top:50%;width:74px;height:74px;transform:translate(-50%,-50%);border:1px solid rgba(255,255,255,.55);border-radius:50%}'
        '.s06-center-line,.s06-center-circle{display:none}.s06-line{position:relative;z-index:1;display:flex;align-items:center;justify-content:center;gap:clamp(2px,1.6vw,8px);min-height:72px;width:100%}'
        '.s06-token{box-sizing:border-box;display:flex;min-width:0;flex:0 1 23%;flex-direction:column;align-items:center;text-align:center}'
        '.s06-circle{display:flex;align-items:center;justify-content:center;width:34px;height:34px;border:2px solid #d5f5db;border-radius:50%;background:#13734b;color:#fff;font-weight:800;font-size:15px;box-shadow:0 2px 4px rgba(0,0,0,.32)}'
        '.s06-nameplate{display:block;box-sizing:border-box;max-width:100%;margin-top:3px;padding:3px 4px;border-radius:5px;background:#10252b;color:#fff;font-size:clamp(9px,2.55vw,12px);font-weight:700;overflow-wrap:anywhere;word-break:normal}'
        '.s06-nameplate small{display:block;color:#bfe6ca;font-size:clamp(8px,2.2vw,10px);font-weight:600}.s06-badge{display:inline-block;margin-left:3px;padding:1px 3px;border-radius:3px;background:#f6c945;color:#2d2600;font-size:9px;font-weight:900;vertical-align:middle}.s06-missing{color:#ffd7d7;font-size:11px;font-weight:700}.s06-bench-card{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:5px;margin-top:8px;padding:9px;border-radius:12px;background:#10252b;color:#fff;font-size:clamp(10px,2.7vw,12px)}.s06-bench-card>strong{grid-column:1/-1;color:#bfe6ca}.s06-bench-slot{min-width:0;padding:5px;border:1px solid rgba(191,230,202,.3);border-radius:6px;text-align:center}.s06-bench-slot strong,.s06-bench-slot span{display:block;overflow-wrap:anywhere}.s06-bench-slot span{margin-top:3px;font-weight:650}@media(max-width:390px){.s06-field-markings{min-height:330px;padding-left:2px;padding-right:2px}.s06-circle{width:30px;height:30px;font-size:13px}.s06-nameplate{padding-left:2px;padding-right:2px;font-size:9px}.s06-line{gap:1px}}@media(min-width:391px) and (max-width:430px){.s06-field-markings{min-height:370px}}'
        '</style>'
    )
    return style + (
        '<section class="s06-dashboard" aria-label="Starting XI dashboard">'
        '<div class="s06-pitch" role="img" aria-label="Canonical Starting XI pitch">'
        '<div class="s06-pitch-header"><strong>Starting XI · %s</strong>'
        '<span>XI xPts %s · captain-adjusted xPts %s</span></div>'
        '<div class="s06-field-markings"><span class="s06-center-line"></span><span class="s06-center-circle"></span>%s</div>'
        '</div>'
        '<div class="s06-bench-card"><strong>Bench · autosub order</strong>%s</div>'
        '%s'
        '</section>'
        % (formation, base, adjusted, "".join(layers), bench_rows, render_s06_formation_frontier(content))
    )
