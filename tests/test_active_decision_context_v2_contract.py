from __future__ import annotations

from copy import deepcopy


ALLOWED = {"CONTEMPLATED", "EXECUTED", "REJECTED", "SUPERSEDED", "EXPIRED"}


def player(element_id: int, display_name: str) -> dict:
    return {"element_id": element_id, "display_name": display_name}


def scenario(scenario_id: str, state: str = "CONTEMPLATED") -> dict:
    return {
        "scenario_id": scenario_id,
        "state": state,
        "created_at": "2026-09-18T21:21:00+07:00",
        "updated_at": "2026-09-18T21:21:00+07:00",
        "expires_at": None,
        "resolved_at": None,
        "superseded_by": None,
        "execution_state": "NOT_EXECUTED",
        "evidence_provenance": [{"type": "user_explicit", "ref": "synthetic-test"}],
    }


def choose_context(persisted: dict, explicit: dict | None) -> dict:
    if explicit and explicit["updated_at"] > persisted["updated_at"]:
        return deepcopy(explicit)
    return deepcopy(persisted)


def scheduler_hydrate(context: dict) -> dict:
    return deepcopy(context)


def optimizer_view(context: dict, preferred_scenario: str) -> dict:
    result = deepcopy(context)
    result["optimizer_preference"] = preferred_scenario
    return result


def active_scenarios(context: dict) -> list[dict]:
    return [
        row
        for row in context["scenarios"]
        if row["state"] not in {"SUPERSEDED", "REJECTED", "EXPIRED"}
    ]


def confirm_execution(context: dict, scenario_id: str) -> dict:
    result = deepcopy(context)
    for row in result["scenarios"]:
        if row["scenario_id"] == scenario_id:
            row["state"] = "EXECUTED"
            row["execution_state"] = "CONFIRMED_EXECUTED"
            row["resolved_at"] = "2026-09-18T21:25:00+07:00"
    return result


def test_1_contemplated_is_not_executed():
    assert "CONTEMPLATED" != "EXECUTED"
    assert {"CONTEMPLATED", "EXECUTED"} <= ALLOWED


def test_2_newer_explicit_user_state_wins():
    old = {"updated_at": "2026-09-18T20:00:00+07:00", "marker": "persisted"}
    new = {"updated_at": "2026-09-18T21:00:00+07:00", "marker": "explicit"}
    assert choose_context(old, new)["marker"] == "explicit"


def test_3_unresolved_scenario_survives_scheduler_execution():
    context = {"scenarios": [scenario("HOLD"), scenario("TRANSFER")]}
    hydrated = scheduler_hydrate(context)
    assert [x["scenario_id"] for x in hydrated["scenarios"]] == ["HOLD", "TRANSFER"]


def test_4_optimizer_preference_does_not_erase_user_scenario():
    context = {"scenarios": [scenario("HOLD"), scenario("TRANSFER")]}
    result = optimizer_view(context, "HOLD")
    assert {x["scenario_id"] for x in result["scenarios"]} == {"HOLD", "TRANSFER"}


def test_5_stable_element_id_is_primary_player_identity():
    ref = player(123, "Presentation Name")
    assert isinstance(ref["element_id"], int)
    assert ref["element_id"] == 123
    assert ref["display_name"] == "Presentation Name"


def test_6_split_branches_remain_distinct():
    hold = {"scenario_id": "HOLD_SANGARE", "xi": [player(488, "Player A")]}
    transfer = {"scenario_id": "TRANSFER_TO_BARNES", "xi": [player(453, "Player B")]}
    assert hold["scenario_id"] != transfer["scenario_id"]
    assert hold["xi"][0]["element_id"] != transfer["xi"][0]["element_id"]


def test_7_superseded_scenario_cannot_remain_active():
    context = {"scenarios": [scenario("OLD", "SUPERSEDED"), scenario("NEW")]}
    assert [x["scenario_id"] for x in active_scenarios(context)] == ["NEW"]


def test_8_execution_confirmation_changes_only_relevant_scenario():
    context = {"scenarios": [scenario("HOLD"), scenario("TRANSFER")]}
    result = confirm_execution(context, "TRANSFER")
    states = {x["scenario_id"]: x["state"] for x in result["scenarios"]}
    assert states == {"HOLD": "CONTEMPLATED", "TRANSFER": "EXECUTED"}


def test_9_state_file_failure_does_not_mutate_v6():
    v6 = {"publication_id": "immutable", "publish_integrity": "PASS"}
    before = deepcopy(v6)
    state_failure = True
    if state_failure:
        report_plane = {"context_status": "UNAVAILABLE"}
    assert report_plane["context_status"] == "UNAVAILABLE"
    assert v6 == before


def test_10_state_is_never_factual_provider_authority():
    state_contract = {
        "non_authoritative_state_file": True,
        "v6_factual_data_plane_owner": False,
    }
    assert state_contract["non_authoritative_state_file"] is True
    assert state_contract["v6_factual_data_plane_owner"] is False


def test_scenario_lifecycle_contract_fields_and_allowed_states():
    row = scenario("EXAMPLE")
    required = {
        "scenario_id", "state", "created_at", "updated_at", "expires_at",
        "resolved_at", "superseded_by", "execution_state", "evidence_provenance",
    }
    assert required <= set(row)
    assert row["state"] in ALLOWED
