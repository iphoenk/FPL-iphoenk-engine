from __future__ import annotations

import subprocess
from pathlib import Path

from tools.v4_architecture_guard_attest import main as attest


BRANCH = "codex/v4-reconciliation-rollover-green"


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    assert count == 1, f"{label}: expected one replacement target, found {count}"
    return text.replace(old, new, 1)


def test_build_rollover_safe_reconciliation_patch() -> None:
    subprocess.run(["git", "checkout", "-B", BRANCH, f"origin/{BRANCH}"], check=True)

    raw_path = Path("src/services/raw_snapshot_service.py")
    raw = raw_path.read_text()
    helper_anchor = '''def run(mode: str = "daily", as_of: str | None = None) -> dict:\n'''
    helper = '''def _pending_reconciliation_actuals_gw(phase: dict) -> int | None:\n    """Return a finished GW whose immutable forecast still needs Official actuals.\n\n    This is acquisition scheduling only. Validation remains the sole lifecycle\n    authority. The raw snapshot may fetch one prior event-live payload after an\n    Official rollover, but only when a leakage-safe deadline snapshot exists and\n    no immutable reconciliation archive has been created yet.\n    """\n    finished_gw = int(phase.get("last_finished_gw") or 0)\n    scoring_gw = int(phase.get("scoring_gw") or 0)\n    if not finished_gw or finished_gw == scoring_gw:\n        return None\n    deadline = DATA / "validation" / "deadline" / f"gw{finished_gw:02d}.json"\n    archive = DATA / "validation" / "archive" / "reconciled" / f"gw{finished_gw:02d}.json"\n    if deadline.exists() and not archive.exists():\n        return finished_gw\n    return None\n\n\n'''
    raw = _replace_once(raw, helper_anchor, helper + helper_anchor, "raw helper anchor")

    old_dependent = '''    submitted_gw, scoring_gw = phase["submitted_gw"], phase["scoring_gw"]\n\n    dependent_specs = []\n    if submitted_gw:\n        dependent_specs.append(("picks", f"entry/{TEAM_ID}/event/{submitted_gw}/picks/", API_RETRIES))\n    if scoring_gw:\n        dependent_specs.append(("event_live", f"event/{scoring_gw}/live/", API_RETRIES))\n    wave_started = perf_counter()\n'''
    new_dependent = '''    submitted_gw, scoring_gw = phase["submitted_gw"], phase["scoring_gw"]\n    reconciliation_gw = _pending_reconciliation_actuals_gw(phase)\n\n    dependent_specs = []\n    if submitted_gw:\n        dependent_specs.append(("picks", f"entry/{TEAM_ID}/event/{submitted_gw}/picks/", API_RETRIES))\n    if scoring_gw:\n        dependent_specs.append(("event_live", f"event/{scoring_gw}/live/", API_RETRIES))\n    if reconciliation_gw:\n        dependent_specs.append(("reconciliation_event_live", f"event/{reconciliation_gw}/live/", API_RETRIES))\n    wave_started = perf_counter()\n'''
    raw = _replace_once(raw, old_dependent, new_dependent, "raw dependent acquisition")

    old_normalize = '''    _normalize_endpoint_health(health, payloads, submitted_gw, scoring_gw, bool(phase.get("is_live_match")))\n\n    teams, positions, by_id = maps(bootstrap)\n'''
    new_normalize = '''    _normalize_endpoint_health(health, payloads, submitted_gw, scoring_gw, bool(phase.get("is_live_match")))\n    reconciliation_actuals = (\n        {\n            "event": int(reconciliation_gw),\n            "source_key": "reconciliation_event_live",\n            "endpoint_status": (health.get("reconciliation_event_live") or {}).get("status"),\n        }\n        if reconciliation_gw\n        else None\n    )\n\n    teams, positions, by_id = maps(bootstrap)\n'''
    raw = _replace_once(raw, old_normalize, new_normalize, "raw reconciliation metadata")

    old_out = '''        "official": payloads,\n        "endpoint_health": health,\n        "authority_policy": {"primary": "PUBLIC_OFFICIAL_PLUS_USER_CAPTURE", "public_official": "UNIVERSAL_FACTUAL_BACKBONE", "user_capture": "PRIVATE_PREDEADLINE_OVERRIDE", "authenticated_official": "OPTIONAL_PRIVATE_ENRICHMENT", "authenticated_official_production_blocking": False},\n'''
    new_out = '''        "official": payloads,\n        "endpoint_health": health,\n        "reconciliation_actuals": reconciliation_actuals,\n        "authority_policy": {"primary": "PUBLIC_OFFICIAL_PLUS_USER_CAPTURE", "public_official": "UNIVERSAL_FACTUAL_BACKBONE", "user_capture": "PRIVATE_PREDEADLINE_OVERRIDE", "authenticated_official": "OPTIONAL_PRIVATE_ENRICHMENT", "authenticated_official_production_blocking": False},\n'''
    raw = _replace_once(raw, old_out, new_out, "raw output metadata")

    old_timing = '''            "official_snapshot_refreshed_this_run": True,\n        },\n'''
    new_timing = '''            "official_snapshot_refreshed_this_run": True,\n            "reconciliation_event_live_requested": bool(reconciliation_gw),\n            "reconciliation_event": int(reconciliation_gw) if reconciliation_gw else None,\n        },\n'''
    raw = _replace_once(raw, old_timing, new_timing, "raw acquisition timing")
    raw_path.write_text(raw)

    lifecycle_path = Path("src/engines/v4_validation_cycle.py")
    lifecycle = lifecycle_path.read_text()
    old_lifecycle = '''    scoring_gw = phase.get("scoring_gw")\n    if int(scoring_gw or -1) != int(gw):\n        return {"status": "SKIP", "reason": "raw_snapshot_does_not_carry_finished_gw_actuals", "gw": int(gw), "scoring_gw": scoring_gw}\n    live = ((raw.get("official") or {}).get("event_live") or {})\n    if not list(live.get("elements") or []):\n        return {"status": "SKIP", "reason": "finished_live_unavailable_in_raw_snapshot", "gw": int(gw)}\n    result = reconcile_finished_gw(int(gw), live, now=now)\n'''
    new_lifecycle = '''    scoring_gw = phase.get("scoring_gw")\n    source_key = "event_live"\n    if int(scoring_gw or -1) != int(gw):\n        reconciliation_actuals = raw.get("reconciliation_actuals") or {}\n        if int(reconciliation_actuals.get("event") or -1) != int(gw):\n            return {\n                "status": "SKIP",\n                "reason": "raw_snapshot_reconciliation_actuals_event_mismatch",\n                "gw": int(gw),\n                "scoring_gw": scoring_gw,\n                "actuals_event": reconciliation_actuals.get("event"),\n            }\n        if reconciliation_actuals.get("source_key") != "reconciliation_event_live":\n            return {\n                "status": "SKIP",\n                "reason": "raw_snapshot_reconciliation_actuals_source_invalid",\n                "gw": int(gw),\n                "scoring_gw": scoring_gw,\n            }\n        source_key = "reconciliation_event_live"\n    live = ((raw.get("official") or {}).get(source_key) or {})\n    if not list(live.get("elements") or []):\n        return {\n            "status": "SKIP",\n            "reason": "finished_live_unavailable_in_raw_snapshot",\n            "gw": int(gw),\n            "actuals_source_key": source_key,\n        }\n    result = reconcile_finished_gw(int(gw), live, now=now)\n'''
    lifecycle = _replace_once(lifecycle, old_lifecycle, new_lifecycle, "validation rollover actuals")

    old_return = '''        "model_version": result.get("model_version"), "actual_elements": result.get("actual_elements"),\n        "official_start_evidence_elements": result.get("official_start_evidence_elements"),\n    }\n'''
    new_return = '''        "model_version": result.get("model_version"), "actual_elements": result.get("actual_elements"),\n        "official_start_evidence_elements": result.get("official_start_evidence_elements"),\n        "actuals_source_key": source_key,\n    }\n'''
    lifecycle = _replace_once(lifecycle, old_return, new_return, "validation source evidence")

    old_guardrail = '''            "preloaded_snapshot_contract_equivalent": True,\n'''
    new_guardrail = '''            "preloaded_snapshot_contract_equivalent": True,\n            "rollover_actuals_acquired_by_raw_snapshot_only": True,\n            "rollover_actuals_event_bound": True,\n'''
    lifecycle = _replace_once(lifecycle, old_guardrail, new_guardrail, "validation rollover guardrails")
    lifecycle_path.write_text(lifecycle)

    Path("tests/test_v4_reconciliation_rollover.py").write_text('''from __future__ import annotations\n\nfrom datetime import datetime, timezone\n\nimport src.engines.v4_backtest_store as store\nimport src.engines.v4_validation_cycle as lifecycle\nimport src.services.raw_snapshot_service as raw_service\n\n\nMODEL = "v4.9.2-truthful-health"\nDEADLINE = "2026-08-28T17:30:00+00:00"\nPRE = datetime(2026, 8, 27, 10, 0, tzinfo=timezone.utc)\nPOST = datetime(2026, 9, 1, 4, 0, tzinfo=timezone.utc)\n\n\ndef _prediction():\n    return {\n        "generated_at": "2026-08-27T09:00:00+00:00",\n        "model_version": MODEL,\n        "players": [{\n            "element": 1, "name": "A", "position": "MID",\n            "fixtures": [{\n                "event": 2, "xpts": 5.0, "lower80": 1.0, "upper80": 9.0,\n                "xmins": {"expected_minutes": 80, "start_probability": 0.9, "p60": 0.8},\n            }],\n        }],\n    }\n\n\ndef _live():\n    return {"elements": [{"id": 1, "stats": {"total_points": 7, "minutes": 90, "starts": 1}}]}\n\n\ndef _isolate_store(monkeypatch, tmp_path):\n    monkeypatch.setattr(store, "SNAPDIR", tmp_path / "validation" / "deadline")\n    monkeypatch.setattr(store, "ARCHIVE_RECDIR", tmp_path / "validation" / "archive" / "reconciled")\n    monkeypatch.setattr(store, "RECDIR", tmp_path / "validation" / "reconciled")\n\n\ndef test_raw_snapshot_requests_rollover_actuals_only_while_reconciliation_pending(monkeypatch, tmp_path):\n    monkeypatch.setattr(raw_service, "DATA", tmp_path)\n    phase = {"last_finished_gw": 2, "scoring_gw": 3}\n    deadline = tmp_path / "validation" / "deadline" / "gw02.json"\n    deadline.parent.mkdir(parents=True)\n    deadline.write_text("{}")\n\n    assert raw_service._pending_reconciliation_actuals_gw(phase) == 2\n\n    archive = tmp_path / "validation" / "archive" / "reconciled" / "gw02.json"\n    archive.parent.mkdir(parents=True)\n    archive.write_text("{}")\n    assert raw_service._pending_reconciliation_actuals_gw(phase) is None\n    assert raw_service._pending_reconciliation_actuals_gw({"last_finished_gw": 2, "scoring_gw": 2}) is None\n\n\ndef test_validation_reconciles_event_bound_rollover_payload(monkeypatch, tmp_path):\n    _isolate_store(monkeypatch, tmp_path)\n    store.persist_deadline_snapshot(2, DEADLINE, _prediction(), now=PRE)\n    raw = {\n        "schema": "snapshot.v1",\n        "as_of": None,\n        "checkpoint_context": {"is_simulation": False},\n        "phase": {"last_finished_gw": 2, "scoring_gw": 3},\n        "reconciliation_actuals": {"event": 2, "source_key": "reconciliation_event_live", "endpoint_status": "LIVE"},\n        "official": {"event_live": {}, "reconciliation_event_live": _live()},\n    }\n\n    result = lifecycle.reconcile_latest_finished(raw, now=POST)\n\n    assert result["status"] == "PASS"\n    assert result["action"] == "CREATED"\n    assert result["gw"] == 2\n    assert result["actuals_source_key"] == "reconciliation_event_live"\n    assert result["actual_elements"] == 1\n\n\ndef test_validation_rejects_rollover_actuals_event_mismatch(monkeypatch, tmp_path):\n    _isolate_store(monkeypatch, tmp_path)\n    store.persist_deadline_snapshot(2, DEADLINE, _prediction(), now=PRE)\n    raw = {\n        "schema": "snapshot.v1",\n        "as_of": None,\n        "checkpoint_context": {"is_simulation": False},\n        "phase": {"last_finished_gw": 2, "scoring_gw": 3},\n        "reconciliation_actuals": {"event": 1, "source_key": "reconciliation_event_live"},\n        "official": {"reconciliation_event_live": _live()},\n    }\n\n    result = lifecycle.reconcile_latest_finished(raw, now=POST)\n\n    assert result["status"] == "SKIP"\n    assert result["reason"] == "raw_snapshot_reconciliation_actuals_event_mismatch"\n    assert not store.reconciled_path(2).exists()\n\n\ndef test_validation_preserves_same_gw_event_live_contract(monkeypatch, tmp_path):\n    _isolate_store(monkeypatch, tmp_path)\n    store.persist_deadline_snapshot(2, DEADLINE, _prediction(), now=PRE)\n    raw = {\n        "schema": "snapshot.v1",\n        "as_of": None,\n        "checkpoint_context": {"is_simulation": False},\n        "phase": {"last_finished_gw": 2, "scoring_gw": 2},\n        "official": {"event_live": _live()},\n    }\n\n    result = lifecycle.reconcile_latest_finished(raw, now=POST)\n\n    assert result["status"] == "PASS"\n    assert result["actuals_source_key"] == "event_live"\n''')

    attest()

    Path(__file__).unlink()
    subprocess.run(["git", "config", "user.name", "fpl-iphoenk-bot"], check=True)
    subprocess.run(["git", "config", "user.email", "actions@users.noreply.github.com"], check=True)
    subprocess.run(["git", "add", "src/services/raw_snapshot_service.py", "src/engines/v4_validation_cycle.py", "tests/test_v4_reconciliation_rollover.py", "config/architecture_guard_attestation.json", str(Path(__file__))], check=True)
    subprocess.run(["git", "commit", "-m", "fix(v4): preserve finished-GW reconciliation across rollover"], check=True)
    subprocess.run(["git", "push", "origin", f"HEAD:{BRANCH}"], check=True)
