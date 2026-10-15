from __future__ import annotations

"""Read-only FotMob public match page JSON extraction under original V6 budget.

Never bypass FotMob access controls: denied or missing pages remain unavailable.
The original HTML response bytes are kept by the V6 source record so its SHA
is auditable. No model probabilities, source time travel or role inference.
"""

from html.parser import HTMLParser
import json
from typing import Any, Mapping


class _NextData(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.capture = False
        self.parts: list[str] = []
        self.count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return
        props = dict(attrs)
        if props.get("id") == "__NEXT_DATA__":
            self.count += 1
            self.capture = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script":
            self.capture = False

    def handle_data(self, data: str) -> None:
        if self.capture:
            self.parts.append(data)


def extract_verified_page_matchdetails(body: str, native_id: int) -> dict[str, Any] | None:
    """Accept original FotMob SSR pageProps only when source identity agrees.

    This is NOT an as-of deadline witness and does not resolve Official FPL
    athlete IDs or semantic tactical roles. Normalizer enforces team/fixture
    crosswalk and formations separately.
    """
    if not isinstance(body, str) or not 0 < len(body) <= 2_500_000:
        return None
    if not isinstance(native_id, int) or isinstance(native_id, bool) or native_id <= 0:
        return None
    parser = _NextData()
    try:
        parser.feed(body)
        if parser.count != 1 or not parser.parts:
            return None
        document = json.loads("".join(parser.parts))
    except (ValueError, TypeError, OverflowError):
        return None
    if not isinstance(document, Mapping):
        return None
    props = document.get("props") or {}
    if not isinstance(props, Mapping):
        return None
    page = props.get("pageProps") or {}
    if not isinstance(page, Mapping):
        return None
    general = page.get("general") or {}
    content = page.get("content") or {}
    if not isinstance(general, Mapping) or not isinstance(content, Mapping):
        return None
    if str(general.get("matchId")) != str(native_id) or str(general.get("leagueId")) != "47":
        return None
    if general.get("finished") is not True:
        return None
    sides = (general.get("homeTeam"), general.get("awayTeam"))
    for side in sides:
        if not isinstance(side, Mapping):
            return None
        try:
            if int(side.get("id") or 0) <= 0:
                return None
        except (TypeError, ValueError):
            return None
    lineup = content.get("lineup")
    if not isinstance(lineup, Mapping):
        return None
    for label in ("homeTeam", "awayTeam"):
        row = lineup.get(label)
        if not isinstance(row, Mapping):
            return None
        starters = row.get("starters")
        if not isinstance(starters, list):
            return None
        if len(starters) != 11:
            return None
    result = {"general": dict(general), "content": dict(content)}
    for optional in ("header", "nav"):
        value = page.get(optional)
        if isinstance(value, Mapping):
            result[optional] = dict(value)
    return result
