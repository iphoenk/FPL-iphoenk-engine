from __future__ import annotations

import json

from src.engines import owned_challenger_transfer_context as transfer_context


def test_transfer_context_updates_comparator_for_active_wildcard(tmp_path, monkeypatch):
    data = tmp_path
    comparator_path = data / "owned_challenger_comparator.json"
    comparator_path.write_text(json.dumps({
        "contract": "OWNED_CHALLENGER_COMPARATOR_V1",
        "comparisons": [{
            "player_out": {"element": 1},
            "player_in": {"element": 2},
            "decision": "LEAN_TRANSFER",
            "decision_risks": [],
            "opportunity_cost": {},
        }],
        "top_comparisons": [{"player_out": {"element": 1}, "player_in": {"element": 2}, "decision": "LEAN_TRANSFER"}],
        "governance": {},
    }))
    (data / "team.json").write_text(json.dumps({
        "projection_baseline": {
            "override_applied": True,
            "override_kind": "WILDCARD",
            "override_target_gw": 2,
            "effective_authority": "LOCKED_PRE_DEADLINE",
            "authority_source": "USER_LOCK",
        }
    }))
    monkeypatch.setattr(transfer_context, "DATA", data)
    monkeypatch.setattr(transfer_context, "OUT", comparator_path)
    result = transfer_context.run()
    assert result["chip"] == "WILDCARD"
    payload = json.loads(comparator_path.read_text())
    row = payload["comparisons"][0]
    assert row["opportunity_cost"]["free_transfer_cost_applied"] is False
    assert row["opportunity_cost"]["hit_cost_applied"] is False
    assert payload["top_comparisons"][0]["opportunity_cost"]["state"] == "WILDCARD_ACTIVE"
