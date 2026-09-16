from __future__ import annotations

"""Deterministic full-universe RISE20/FALL20 construction.

R3 owns selection, ordering, rank assignment, ownership tagging, truthful ETA
presentation, and snapshot provenance binding. It deliberately does not invent a
price model: normalized predictor values such as projection, urgency, confidence,
and predicted cycle remain upstream MODEL inputs.
"""

from math import isfinite
from typing import Any, Iterable, Mapping, Sequence

from .delivery_integrity import validate_rank20
from .temporal import DEFAULT_RUNTIME_TIMEZONE, TemporalError, parse_timestamp


class Rank20EngineError(ValueError):
    pass


_SNAPSHOT_FIELDS = ("source", "observed_at", "raw_payload_hash")
_MODEL_FIELDS = (
    "current_progress_percent",
    "projection_offset_0_percent",
    "predicted_change_cycle",
    "predicted_change_at",
    "eta_human",
    "model_urgency",
    "confidence",
)


def _require_element_id(row: Mapping[str, Any], *, scope: str, index: int) -> int | str:
    element_id = row.get("element_id")
    if element_id is None or isinstance(element_id, bool) or str(element_id).strip() == "":
        raise Rank20EngineError(f"{scope}_ID_MISSING:{index}")
    return element_id


def _index_unique(
    rows: Sequence[Mapping[str, Any]],
    *,
    scope: str,
) -> dict[int | str, Mapping[str, Any]]:
    indexed: dict[int | str, Mapping[str, Any]] = {}
    for index, row in enumerate(rows, start=1):
        element_id = _require_element_id(row, scope=scope, index=index)
        if element_id in indexed:
            raise Rank20EngineError(f"{scope}_ID_DUPLICATE:{element_id}")
        indexed[element_id] = row
    return indexed


def _numeric(value: Any, *, label: str, element_id: int | str) -> float:
    if value is None or isinstance(value, bool):
        raise Rank20EngineError(f"{label}_MISSING:{element_id}")
    try:
        resolved = float(value)
    except (TypeError, ValueError) as exc:
        raise Rank20EngineError(f"{label}_INVALID:{element_id}") from exc
    if not isfinite(resolved):
        raise Rank20EngineError(f"{label}_INVALID:{element_id}")
    return resolved


def _non_empty(value: Any, *, label: str, element_id: int | str) -> str:
    text = str(value or "").strip()
    if not text:
        raise Rank20EngineError(f"{label}_MISSING:{element_id}")
    return text


def _is_sha256(value: Any) -> bool:
    text = str(value or "").strip()
    return len(text) == 64 and all(character in "0123456789abcdefABCDEF" for character in text)


def _canonical_snapshot(snapshot: Mapping[str, Any]) -> dict[str, str]:
    source = str(snapshot.get("source") or "").strip()
    observed_at = str(snapshot.get("observed_at") or "").strip()
    raw_payload_hash = str(snapshot.get("raw_payload_hash") or "").strip().lower()
    if not source:
        raise Rank20EngineError("SNAPSHOT_SOURCE_MISSING")
    if not observed_at:
        raise Rank20EngineError("SNAPSHOT_OBSERVED_AT_MISSING")
    try:
        parse_timestamp(observed_at, label="snapshot observed_at")
    except TemporalError as exc:
        raise Rank20EngineError("SNAPSHOT_OBSERVED_AT_INVALID") from exc
    if not _is_sha256(raw_payload_hash):
        raise Rank20EngineError("SNAPSHOT_HASH_INVALID")
    return {
        "source": source,
        "observed_at": observed_at,
        "raw_payload_hash": raw_payload_hash,
    }


def _same_instant(left: Any, right: Any) -> bool:
    try:
        return parse_timestamp(str(left), label="left") == parse_timestamp(str(right), label="right")
    except TemporalError:
        return False


def _assert_row_snapshot(
    row: Mapping[str, Any],
    *,
    snapshot: Mapping[str, str],
    element_id: int | str,
) -> None:
    if "source" in row and str(row.get("source") or "").strip() != snapshot["source"]:
        raise Rank20EngineError(f"SNAPSHOT_PROVENANCE_MISMATCH:{element_id}:source")
    if "raw_payload_hash" in row:
        row_hash = str(row.get("raw_payload_hash") or "").strip().lower()
        if row_hash != snapshot["raw_payload_hash"]:
            raise Rank20EngineError(f"SNAPSHOT_PROVENANCE_MISMATCH:{element_id}:raw_payload_hash")
    if "observed_at" in row and not _same_instant(row.get("observed_at"), snapshot["observed_at"]):
        raise Rank20EngineError(f"SNAPSHOT_PROVENANCE_MISMATCH:{element_id}:observed_at")


def _stable_id_key(element_id: int | str) -> tuple[int, Any]:
    if isinstance(element_id, int) and not isinstance(element_id, bool):
        return (0, element_id)
    text = str(element_id).strip()
    try:
        return (0, int(text))
    except ValueError:
        return (1, text)


def _eta_human(row: Mapping[str, Any], *, element_id: int | str) -> tuple[Any, str]:
    predicted_change_at = row.get("predicted_change_at")
    eta_human = str(row.get("eta_human") or "").strip()
    if predicted_change_at not in {None, ""}:
        try:
            parsed = parse_timestamp(
                str(predicted_change_at),
                label=f"predicted_change_at:{element_id}",
                target_timezone=DEFAULT_RUNTIME_TIMEZONE,
            )
        except TemporalError as exc:
            raise Rank20EngineError(f"PREDICTED_CHANGE_AT_INVALID:{element_id}") from exc
        if not eta_human:
            eta_human = parsed.strftime("%Y-%m-%d %H:%M WIB")
    elif not eta_human:
        eta_human = "NO RELIABLE ETA"
    return predicted_change_at, eta_human


def _materialize_candidate(
    *,
    official: Mapping[str, Any],
    predictor: Mapping[str, Any],
    owned_ids: set[int | str],
    snapshot: Mapping[str, str],
) -> dict[str, Any]:
    element_id = official["element_id"]
    _assert_row_snapshot(predictor, snapshot=snapshot, element_id=element_id)

    player_name = _non_empty(
        official.get("player_name"),
        label="PLAYER_NAME",
        element_id=element_id,
    )
    progress = _numeric(
        predictor.get("current_progress_percent"),
        label="CURRENT_PROGRESS",
        element_id=element_id,
    )
    projection = _numeric(
        predictor.get("projection_offset_0_percent"),
        label="PROJECTION_OFFSET",
        element_id=element_id,
    )
    cycle = _non_empty(
        predictor.get("predicted_change_cycle"),
        label="PREDICTED_CHANGE_CYCLE",
        element_id=element_id,
    )
    urgency = _non_empty(
        predictor.get("model_urgency"),
        label="MODEL_URGENCY",
        element_id=element_id,
    )
    confidence = _non_empty(
        predictor.get("confidence"),
        label="CONFIDENCE",
        element_id=element_id,
    )
    predicted_change_at, eta_human = _eta_human(predictor, element_id=element_id)

    return {
        "element_id": element_id,
        "player_name": player_name,
        "current_price": official.get("current_price"),
        "ownership_percent": official.get("ownership_percent"),
        "ownership_tag": "OWNED" if element_id in owned_ids else "NON_OWNED",
        "current_progress_percent": progress,
        "projection_offset_0_percent": projection,
        "predicted_change_cycle": cycle,
        "predicted_change_at": predicted_change_at,
        "eta_human": eta_human,
        "model_urgency": urgency,
        "confidence": confidence,
        **snapshot,
    }


def _rank(
    candidates: Sequence[Mapping[str, Any]],
    *,
    direction: str,
) -> list[dict[str, Any]]:
    if direction not in {"RISE", "FALL"}:
        raise Rank20EngineError(f"DIRECTION_INVALID:{direction}")

    reverse_projection = direction == "RISE"
    if reverse_projection:
        ordered = sorted(
            candidates,
            key=lambda row: (
                -float(row["projection_offset_0_percent"]),
                _stable_id_key(row["element_id"]),
            ),
        )
    else:
        ordered = sorted(
            candidates,
            key=lambda row: (
                float(row["projection_offset_0_percent"]),
                _stable_id_key(row["element_id"]),
            ),
        )

    ranked: list[dict[str, Any]] = []
    for rank, candidate in enumerate(ordered[:20], start=1):
        ranked.append({"rank": rank, **candidate, "direction": direction})
    return ranked


def build_rank20_tables(
    *,
    universe_rows: Sequence[Mapping[str, Any]],
    predictor_rows: Sequence[Mapping[str, Any]],
    owned_ids: Iterable[int | str] = (),
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Build deterministic exact-20 RISE/FALL rows from one full-universe snapshot.

    COMPLETE R3 computation is intentionally fail-closed. Every current universe
    identity must have one normalized predictor row; partial-source degradation is
    handled by the later report recovery/degradation layer rather than silently
    shrinking the ranking denominator here.
    """
    universe = _index_unique(universe_rows, scope="UNIVERSE")
    predictor = _index_unique(predictor_rows, scope="PREDICTOR")
    if len(universe) < 40:
        raise Rank20EngineError(f"UNIVERSE_TOO_SMALL:{len(universe)}")

    universe_ids = set(universe)
    predictor_ids = set(predictor)
    missing = sorted(universe_ids - predictor_ids, key=_stable_id_key)
    outside = sorted(predictor_ids - universe_ids, key=_stable_id_key)
    if missing:
        raise Rank20EngineError(
            "FULL_UNIVERSE_PREDICTOR_COVERAGE:missing=" + ",".join(map(str, missing[:20]))
        )
    if outside:
        raise Rank20EngineError(
            "PREDICTOR_OUTSIDE_UNIVERSE:" + ",".join(map(str, outside[:20]))
        )

    canonical_snapshot = _canonical_snapshot(snapshot)
    owned = set(owned_ids)
    candidates = [
        _materialize_candidate(
            official=universe[element_id],
            predictor=predictor[element_id],
            owned_ids=owned,
            snapshot=canonical_snapshot,
        )
        for element_id in sorted(universe, key=_stable_id_key)
    ]

    rise = _rank(candidates, direction="RISE")
    fall = _rank(candidates, direction="FALL")

    rise_validation = validate_rank20(rise, label="RISE20")
    fall_validation = validate_rank20(fall, label="FALL20")
    if rise_validation["status"] != "PASS":
        raise Rank20EngineError("RISE20_CONTRACT_FAIL:" + ";".join(rise_validation["failures"]))
    if fall_validation["status"] != "PASS":
        raise Rank20EngineError("FALL20_CONTRACT_FAIL:" + ";".join(fall_validation["failures"]))

    return {
        "RISE20": rise,
        "FALL20": fall,
        "universe_count": len(universe),
        "predictor_coverage_count": len(predictor),
        "full_universe_coverage": True,
        "selection_rule": {
            "RISE20": "projection_offset_0_percent DESC, element_id ASC",
            "FALL20": "projection_offset_0_percent ASC, element_id ASC",
        },
        "snapshot": canonical_snapshot,
    }
