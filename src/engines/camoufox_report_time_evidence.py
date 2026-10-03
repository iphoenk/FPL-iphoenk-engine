from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable


CONTRACT = "report_time_evidence_v1"
_ORIGIN = "CAMOUFOX"
_ROTOWIRE_STATUS_RE = re.compile(r"^(?P<name>.+?)\s+(?P<status>QUES|OUT|SUS)$", re.I)
_PROBABILITY_RE = re.compile(r"\s+\d{1,3}%$")


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def _clean_candidate(value: str) -> str:
    text = _PROBABILITY_RE.sub("", str(value or "").strip())
    text = re.sub(r"^[A-ZÀ-ÖØ-Þ]\.[ ]+", "", text)
    return text.strip(" -–—:\t")


def _official_bootstrap(official_payload: dict[str, Any]) -> dict[str, Any]:
    official = official_payload.get("official") or {}
    bootstrap = official.get("bootstrap") or {}
    return bootstrap if isinstance(bootstrap, dict) else {}


def _player_aliases(bootstrap: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], set[str]]:
    candidates: dict[str, list[dict[str, Any]]] = {}
    for row in bootstrap.get("elements") or []:
        if not isinstance(row, dict):
            continue
        first = str(row.get("first_name") or "").strip()
        second = str(row.get("second_name") or "").strip()
        web = str(row.get("web_name") or "").strip()
        full = " ".join(part for part in (first, second) if part).strip()
        aliases = {web, full, second}
        if second and " " in second:
            aliases.add(second.split()[-1])
        for alias in aliases:
            key = _normalize(alias)
            if not key:
                continue
            candidates.setdefault(key, []).append(row)

    unique: dict[str, dict[str, Any]] = {}
    ambiguous: set[str] = set()
    for key, rows in candidates.items():
        by_id = {int(row.get("id") or 0): row for row in rows if int(row.get("id") or 0) > 0}
        if len(by_id) == 1:
            unique[key] = next(iter(by_id.values()))
        elif len(by_id) > 1:
            ambiguous.add(key)
    return unique, ambiguous


def _resolve_player(
    raw_name: str,
    aliases: dict[str, dict[str, Any]],
    ambiguous: set[str],
) -> dict[str, Any] | None:
    cleaned = _clean_candidate(raw_name)
    variants = [cleaned]
    if " " in cleaned:
        variants.append(cleaned.split()[-1])
    for variant in variants:
        key = _normalize(variant)
        if key and key not in ambiguous and key in aliases:
            return aliases[key]
    return None


def _subject(row: dict[str, Any]) -> str:
    return str(
        row.get("web_name")
        or " ".join(
            part
            for part in (
                str(row.get("first_name") or "").strip(),
                str(row.get("second_name") or "").strip(),
            )
            if part
        )
        or f"element:{row.get('id')}"
    ).strip()


def _signal(
    *,
    capture: dict[str, Any],
    player: dict[str, Any],
    topic: str,
    stance: str,
    summary: str,
    extractor: str,
) -> dict[str, Any]:
    return {
        "source_id": str(capture.get("source_id") or ""),
        "source_class": str(capture.get("source_class") or ""),
        "topic": topic,
        "subject": _subject(player),
        "stance": stance,
        "observed_at": capture.get("observed_at"),
        "source_url": capture.get("final_url") or capture.get("requested_url"),
        "summary": summary,
        "element_id": int(player.get("id") or 0) or None,
        "origin_transport": _ORIGIN,
        "extractor": extractor,
        "capture_sha256": capture.get("content_sha256"),
        "surface_material_news": True,
        "semantic_scope": "DETERMINISTIC_EXPLICIT_AVAILABILITY_ONLY",
    }


def _ffscout_signals(
    capture: dict[str, Any],
    aliases: dict[str, dict[str, Any]],
    ambiguous: set[str],
) -> list[dict[str, Any]]:
    lines = [line.strip() for line in str(capture.get("visible_text") or "").splitlines()]
    lines = [line for line in lines if line]
    mode: str | None = None
    out: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()

    for line in lines:
        marker = line.casefold().rstrip(":")
        if marker == "out":
            mode = "OUT"
            continue
        if marker == "doubts":
            mode = "DOUBT"
            continue
        if marker == "banned":
            mode = "BANNED"
            continue
        if marker in {"latest news", "next match"} or marker.startswith("last updated"):
            mode = None
            continue
        if line.casefold().startswith("next match:"):
            mode = None
            continue
        if mode is None:
            continue

        player = _resolve_player(line, aliases, ambiguous)
        if player is None:
            continue
        player_id = int(player.get("id") or 0)
        if not player_id:
            continue
        status_key = (player_id, mode)
        if status_key in seen:
            continue
        seen.add(status_key)

        if mode == "BANNED":
            topic = "SUSPENSION"
            stance = "BENCH"
            summary = (
                f"FFScout public Team News lists {_subject(player)} as banned."
            )
        elif mode == "OUT":
            topic = "AVAILABILITY"
            stance = "INJURY_RISK"
            summary = (
                f"FFScout public Team News lists {_subject(player)} as out."
            )
        else:
            topic = "AVAILABILITY"
            stance = "INJURY_RISK"
            probability = _PROBABILITY_RE.search(line)
            detail = probability.group(0).strip() if probability else "doubt"
            summary = (
                f"FFScout public Team News lists {_subject(player)} as a {detail}."
            )
        out.append(
            _signal(
                capture=capture,
                player=player,
                topic=topic,
                stance=stance,
                summary=summary,
                extractor="ffscout_public_team_news_v1",
            )
        )
    return out


def _rotowire_signals(
    capture: dict[str, Any],
    aliases: dict[str, dict[str, Any]],
    ambiguous: set[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for raw in str(capture.get("visible_text") or "").splitlines():
        line = raw.strip()
        match = _ROTOWIRE_STATUS_RE.match(line)
        if not match:
            continue
        status = str(match.group("status") or "").upper()
        player = _resolve_player(match.group("name"), aliases, ambiguous)
        if player is None:
            continue
        player_id = int(player.get("id") or 0)
        if not player_id or (player_id, status) in seen:
            continue
        seen.add((player_id, status))

        if status == "SUS":
            topic = "SUSPENSION"
            stance = "BENCH"
            meaning = "suspended"
        elif status == "OUT":
            topic = "AVAILABILITY"
            stance = "INJURY_RISK"
            meaning = "out"
        else:
            topic = "AVAILABILITY"
            stance = "INJURY_RISK"
            meaning = "questionable"

        out.append(
            _signal(
                capture=capture,
                player=player,
                topic=topic,
                stance=stance,
                summary=(
                    f"RotoWire public lineups page marks {_subject(player)} as "
                    f"{meaning} ({status})."
                ),
                extractor="rotowire_public_availability_v1",
            )
        )
    return out


def extract_signals(
    capture_payload: dict[str, Any],
    official_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    if capture_payload.get("contract") != "report_time_web_capture_v1":
        return []
    if capture_payload.get("status") != "READY":
        return []

    bootstrap = _official_bootstrap(official_payload)
    aliases, ambiguous = _player_aliases(bootstrap)
    signals: list[dict[str, Any]] = []
    for capture in capture_payload.get("captures") or []:
        if not isinstance(capture, dict) or capture.get("status") != "AVAILABLE":
            continue
        source_id = str(capture.get("source_id") or "")
        if source_id == "ffscout_editorial":
            signals.extend(_ffscout_signals(capture, aliases, ambiguous))
        elif source_id == "rotowire":
            signals.extend(_rotowire_signals(capture, aliases, ambiguous))
    return signals


def _dedupe(signals: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in signals:
        key = (
            str(row.get("source_id") or ""),
            str(row.get("topic") or ""),
            _normalize(row.get("subject")),
            str(row.get("summary") or "").casefold(),
        )
        if not all(key[:3]) or key in seen:
            continue
        seen.add(key)
        out.append(dict(row))
    return out


def build_evidence(
    *,
    capture_payload: dict[str, Any],
    official_payload: dict[str, Any],
    existing_payload: dict[str, Any] | None = None,
    report_slot: str | None = None,
) -> dict[str, Any]:
    existing = dict(existing_payload or {})
    prior = [
        dict(row)
        for row in existing.get("signals") or []
        if isinstance(row, dict) and row.get("origin_transport") != _ORIGIN
    ]
    fresh = extract_signals(capture_payload, official_payload)
    merged = _dedupe([*prior, *fresh])
    return {
        "contract": CONTRACT,
        "generated_at": capture_payload.get("generated_at"),
        "report_slot": report_slot or capture_payload.get("report_slot"),
        "signals": merged,
        "camoufox": {
            "capture_status": capture_payload.get("status"),
            "capture_count": capture_payload.get("capture_count"),
            "available_count": capture_payload.get("available_count"),
            "deterministic_signal_count": len(fresh),
            "raw_capture_never_promoted_wholesale": True,
            "extractors": [
                "ffscout_public_team_news_v1",
                "rotowire_public_availability_v1",
            ],
        },
    }


def run(
    *,
    capture_path: Path,
    official_path: Path,
    existing_path: Path | None,
    output_path: Path,
    report_slot: str | None = None,
) -> dict[str, Any]:
    capture = _read_json(capture_path, {})
    official = _read_json(official_path, {})
    existing = _read_json(existing_path, {}) if existing_path else {}
    result = build_evidence(
        capture_payload=capture,
        official_payload=official,
        existing_payload=existing,
        report_slot=report_slot,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--official", type=Path, required=True)
    parser.add_argument("--existing", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report-slot", default="")
    args = parser.parse_args()
    result = run(
        capture_path=args.capture,
        official_path=args.official,
        existing_path=args.existing,
        output_path=args.output,
        report_slot=args.report_slot or None,
    )
    print(
        json.dumps(
            {
                "contract": result.get("contract"),
                "signal_count": len(result.get("signals") or []),
                "camoufox": result.get("camoufox"),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
