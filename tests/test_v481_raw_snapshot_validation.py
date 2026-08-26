import pytest

from src.services.raw_snapshot_service import _normalize_endpoint_health, _validate_authoritative_squad


POSITION_TYPE = {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}


def valid_squad():
    rows = []
    by_id = {}
    element = 1
    for position, count in {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}.items():
        for _ in range(count):
            team = ((element - 1) // 3) + 1
            rows.append({"element": element, "position": position})
            by_id[element] = {"id": element, "element_type": POSITION_TYPE[position], "team": team}
            element += 1
    return rows, by_id


def test_authoritative_squad_accepts_legal_structure():
    squad, by_id = valid_squad()
    _validate_authoritative_squad(squad, by_id)


@pytest.mark.parametrize("failure", ["count", "duplicate", "identity", "composition", "club"])
def test_authoritative_squad_fails_closed_on_invalid_structure(failure):
    squad, by_id = valid_squad()
    if failure == "count":
        squad.pop()
    elif failure == "duplicate":
        squad[-1]["element"] = squad[0]["element"]
    elif failure == "identity":
        squad[-1]["position"] = "MID"
    elif failure == "composition":
        squad[-1]["position"] = "MID"
        by_id[squad[-1]["element"]]["element_type"] = POSITION_TYPE["MID"]
    else:
        for element in range(1, 5):
            by_id[element]["team"] = 1

    with pytest.raises(RuntimeError, match="FAIL CLOSED"):
        _validate_authoritative_squad(squad, by_id)


def test_endpoint_health_normalization_is_truthful():
    health = {"picks": {"status": "ERROR"}, "event_live": {"status": "LIVE"}}
    _normalize_endpoint_health(health, {"picks": None}, submitted_gw=1, scoring_gw=1, is_live_event=False)
    assert health["picks"]["status"] == "NOT_YET_AVAILABLE"
    assert health["event_live"]["status"] == "IDLE"

    _normalize_endpoint_health(health, {"picks": {"picks": []}}, submitted_gw=1, scoring_gw=1, is_live_event=True)
    assert health["picks"]["status"] == "LIVE"
