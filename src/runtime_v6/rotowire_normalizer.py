from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

_PLAYER_ID_RE = re.compile(r"/soccer/player/[^?#\"']*-(\d+)(?:[/?#]|$)")
_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


def _clean(parts: list[str]) -> str | None:
    value = " ".join(" ".join(parts).split())
    return value or None


class _RotoWireLineupParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, set[str]]] = []
        self.in_fixture = False
        self.root_attrs: dict[str, str | None] = {}
        self.fixture: dict[str, Any] = {}
        self.fixtures: list[dict[str, Any]] = []
        self.players: list[dict[str, Any]] = []
        self.side_status: dict[str, str] = {}
        self.side_section: dict[str, str] = {}
        self.current_player: dict[str, Any] | None = None
        self.current_player_depth: int | None = None
        self.current_title_side: str | None = None
        self.current_title_depth: int | None = None
        self.current_title_text: list[str] = []

    @staticmethod
    def _classes(attrs: list[tuple[str, str | None]]) -> set[str]:
        raw = dict(attrs).get("class") or ""
        return {part for part in raw.split() if part}

    def _ancestor_has(self, class_name: str) -> bool:
        return any(class_name in classes for _, classes in self.stack)

    def _side(self) -> str | None:
        for _, classes in reversed(self.stack):
            if "is-home" in classes:
                return "home"
            if "is-visit" in classes:
                return "away"
        return None

    def _start_fixture(self, attrs: list[tuple[str, str | None]], classes: set[str]) -> None:
        self.in_fixture = True
        self.stack = [("div", classes)]
        self.root_attrs = dict(attrs)
        self.fixture = {
            "time_text_parts": [],
            "teams": {
                "home": {"name": None, "abbr": None, "text_parts": []},
                "away": {"name": None, "abbr": None, "text_parts": []},
            },
        }
        self.side_status = {}
        self.side_section = {"home": "lineup", "away": "lineup"}
        self.current_player = None
        self.current_player_depth = None
        self.current_title_side = None
        self.current_title_depth = None
        self.current_title_text = []

    def _finish_fixture(self) -> None:
        teams = self.fixture.get("teams") or {}
        for side in ("home", "away"):
            team = teams.get(side) or {}
            if not team.get("name"):
                text = _clean(team.get("text_parts") or [])
                abbr = team.get("abbr")
                if text and abbr and text.startswith(str(abbr)):
                    text = text[len(str(abbr)):].strip() or None
                team["name"] = text
            team.pop("text_parts", None)

        native_id = None
        for key in ("data-gameid", "data-game-id", "data-matchid", "data-match-id"):
            raw = self.root_attrs.get(key)
            if raw:
                try:
                    native_id = int(raw)
                except (TypeError, ValueError):
                    native_id = str(raw)
                break

        time_text = _clean(self.fixture.get("time_text_parts") or [])
        home = teams.get("home") or {}
        away = teams.get("away") or {}
        fixture_key = str(native_id) if native_id is not None else "|".join(
            str(value or "UNKNOWN")
            for value in (time_text, home.get("abbr") or home.get("name"), away.get("abbr") or away.get("name"))
        )
        fixture_index = len(self.fixtures)
        self.fixtures.append(
            {
                "source_native_id": native_id,
                "fixture_key": fixture_key,
                "time_text": time_text,
                "home": {"name": home.get("name"), "abbr": home.get("abbr")},
                "away": {"name": away.get("name"), "abbr": away.get("abbr")},
                "lineup_status": {
                    "home": self.side_status.get("home"),
                    "away": self.side_status.get("away"),
                },
            }
        )
        for player in self.players:
            if player.get("fixture_index") == fixture_index:
                player["fixture_key"] = fixture_key

        self.in_fixture = False
        self.stack = []
        self.root_attrs = {}
        self.fixture = {}
        self.side_status = {}
        self.side_section = {}
        self.current_player = None
        self.current_player_depth = None
        self.current_title_side = None
        self.current_title_depth = None
        self.current_title_text = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = self._classes(attrs)
        if not self.in_fixture:
            if tag == "div" and "lineup" in classes:
                self._start_fixture(attrs, classes)
            return

        if tag not in _VOID_TAGS:
            self.stack.append((tag, classes))

        if tag == "li" and "lineup__status" in classes:
            side = self._side()
            if side:
                if "is-confirmed" in classes:
                    self.side_status[side] = "CONFIRMED"
                elif "is-expected" in classes:
                    self.side_status[side] = "PREDICTED"
                self.side_section[side] = "lineup"

        if tag == "li" and "lineup__title" in classes and "is-middle" in classes:
            self.current_title_side = self._side()
            self.current_title_depth = len(self.stack)
            self.current_title_text = []

        if tag == "li" and "lineup__player" in classes:
            side = self._side()
            self.current_player = {
                "fixture_index": len(self.fixtures),
                "team_side": side,
                "lineup_status": self.side_status.get(side or ""),
                "section": self.side_section.get(side or "", "lineup"),
                "source_native_id": None,
                "player_name": None,
                "position": None,
                "availability_status": None,
                "name_parts": [],
                "position_parts": [],
                "availability_parts": [],
            }
            self.current_player_depth = len(self.stack)

        if tag == "a":
            attrs_dict = dict(attrs)
            side = self._side()
            if side and self._ancestor_has("lineup__mteam"):
                title = attrs_dict.get("title")
                if title:
                    self.fixture["teams"][side]["name"] = title.strip()
            if self.current_player is not None:
                title = attrs_dict.get("title")
                href = attrs_dict.get("href") or ""
                if title:
                    self.current_player["player_name"] = title.strip()
                match = _PLAYER_ID_RE.search(href)
                if match:
                    self.current_player["source_native_id"] = int(match.group(1))

    def handle_data(self, data: str) -> None:
        if not self.in_fixture:
            return
        text = data.strip()
        if not text:
            return

        if self._ancestor_has("lineup__time"):
            self.fixture["time_text_parts"].append(text)

        side = self._side()
        if side and self._ancestor_has("lineup__mteam"):
            self.fixture["teams"][side]["text_parts"].append(text)
            if self._ancestor_has("lineup__abbr"):
                self.fixture["teams"][side]["abbr"] = text

        if self.current_title_side is not None:
            self.current_title_text.append(text)

        if self.current_player is not None:
            if self._ancestor_has("lineup__pos"):
                self.current_player["position_parts"].append(text)
            elif self._ancestor_has("lineup__inj"):
                self.current_player["availability_parts"].append(text)
            elif self.stack and self.stack[-1][0] == "a":
                self.current_player["name_parts"].append(text)

    def handle_endtag(self, tag: str) -> None:
        if not self.in_fixture or not self.stack:
            return

        if (
            self.current_player is not None
            and self.current_player_depth == len(self.stack)
            and self.stack[-1][0] == "li"
            and tag == "li"
        ):
            if not self.current_player.get("player_name"):
                self.current_player["player_name"] = _clean(self.current_player.pop("name_parts"))
            else:
                self.current_player.pop("name_parts", None)
            self.current_player["position"] = _clean(self.current_player.pop("position_parts"))
            self.current_player["availability_status"] = _clean(
                self.current_player.pop("availability_parts")
            )
            self.players.append(self.current_player)
            self.current_player = None
            self.current_player_depth = None

        if (
            self.current_title_side is not None
            and self.current_title_depth == len(self.stack)
            and self.stack[-1][0] == "li"
            and tag == "li"
        ):
            title = (_clean(self.current_title_text) or "").casefold()
            if "injur" in title:
                self.side_section[self.current_title_side] = "injuries"
            elif "lineup" in title or "starter" in title:
                self.side_section[self.current_title_side] = "lineup"
            self.current_title_side = None
            self.current_title_depth = None
            self.current_title_text = []

        if len(self.stack) == 1 and self.stack[-1][0] == "div" and tag == "div":
            self._finish_fixture()
            return

        if self.stack[-1][0] == tag:
            self.stack.pop()
            return
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return


def parse_rotowire_lineups(body: str) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(body, str) or not body.strip():
        return {"fixtures": [], "lineups": [], "availability": []}

    parser = _RotoWireLineupParser()
    try:
        parser.feed(body)
        parser.close()
    except (ValueError, TypeError):
        return {"fixtures": [], "lineups": [], "availability": []}

    fixtures = parser.fixtures
    lineups: list[dict[str, Any]] = []
    availability: list[dict[str, Any]] = []
    fixture_by_index = {index: row for index, row in enumerate(fixtures)}

    for raw in parser.players:
        row = dict(raw)
        fixture_index = int(row.pop("fixture_index"))
        fixture = fixture_by_index.get(fixture_index) or {}
        side = row.get("team_side")
        team = (fixture.get(side) or {}) if side in {"home", "away"} else {}
        row["team_name"] = team.get("name")
        row["team_abbr"] = team.get("abbr")
        row["identity_status"] = "UNMAPPED"
        row["official_element_id"] = None

        if row.get("section") != "injuries" and row.get("lineup_status") in {"CONFIRMED", "PREDICTED"}:
            row["record_semantic_class"] = (
                "NORMALIZED_FACT" if row["lineup_status"] == "CONFIRMED" else "UPSTREAM_MODEL_SIGNAL"
            )
            lineups.append(dict(row))
        if row.get("availability_status"):
            availability_row = dict(row)
            availability_row["record_semantic_class"] = "SECONDARY_AVAILABILITY_SIGNAL"
            availability.append(availability_row)

    return {"fixtures": fixtures, "lineups": lineups, "availability": availability}
