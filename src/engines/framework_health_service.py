from __future__ import annotations

import json
from collections import Counter

from src.engines import framework_health_audit as audit_engine
from src.rules import SQUAD_RULES
from src.settings import NORMAL_STALE_MINUTES
from src.utils import CONFIG, DATA, read_json


def activate_registry_contract() -> dict[str, int]:
    """Make registry-declared counts authoritative for the compatibility audit core."""
    expected: dict[str, int] = {}
    for name, path in audit_engine.REGISTRIES.items():
        payload = json.loads(path.read_text(encoding="utf-8"))
        value = payload.get("expected_count")
        if value is None:
            raise RuntimeError(f"registry {name} missing expected_count")
        count = int(value)
        if count <= 0:
            raise RuntimeError(f"registry {name} expected_count must be positive")
        rows_key = "modules" if name in {"dss_core", "dss_extensions"} else "layers" if name == "enhancements" else "checks"
        declared = len(payload.get(rows_key) or [])
        if declared != count:
            raise RuntimeError(f"registry {name} declared {declared} rows but expected_count={count}")
        expected[name] = count
    # framework_health_audit retains old literals only as an inactive compatibility fallback.
    # The active service always injects registry truth before invoking the audit core.
    audit_engine.EXPECTED_COUNTS = expected
    return expected


def activate_freshness_contract() -> int:
    """Make engine-config freshness the active default used by the compatibility audit core."""
    configured = int(NORMAL_STALE_MINUTES)
    original = audit_engine._probe_freshness

    def configured_probe(max_age_minutes: int | None = None):
        return original(configured if max_age_minutes is None else int(max_age_minutes))

    audit_engine._probe_freshness = configured_probe
    return configured


def activate_canonical_probe_contracts() -> tuple[str, ...]:
    """Replace legacy formula probes with validation of canonical runtime evidence.

    The compatibility audit core still contains historical fallbacks, but the active
    framework-health service must never recompute xMins, player projections or squad
    legality through legacy model modules. It validates canonical projection artifacts
    and authoritative rules instead.
    """

    def canonical_xmins_probe() -> tuple[bool, dict]:
        projections = read_json(DATA / "projections.json", {})
        players = list(projections.get("players") or [])[:25]
        if not players:
            return False, {"reason": "no canonical projection sample"}
        good = 0
        for player in players:
            xmins = player.get("xmins") or {}
            start = float(xmins.get("start_probability") or 0.0)
            bench = float(xmins.get("bench_probability") or 0.0)
            dnp = float(xmins.get("dnp_probability") or 0.0)
            expected = float(xmins.get("expected_minutes") or 0.0)
            availability = float(xmins.get("availability", xmins.get("overall_availability", 1.0)) or 0.0)
            if (
                abs((start + bench + dnp) - 1.0) < audit_engine.XMINS_PROBABILITY_SUM_TOLERANCE
                and 0.0 <= expected <= 90.0
                and 0.0 <= availability <= 1.0
            ):
                good += 1
        return good == len(players), {
            "source": "data/projections.json",
            "sample": len(players),
            "valid": good,
            "recomputed_formula": False,
        }

    def canonical_projection_probe() -> tuple[bool, dict]:
        projections = read_json(DATA / "projections.json", {})
        planning_gw = int(projections.get("planning_gw") or 0)
        players = list(projections.get("players") or [])[:25]
        if not players or planning_gw <= 0:
            return False, {"reason": "canonical planning projections unavailable"}
        good = 0
        for player in players:
            row = next(
                (item for item in player.get("xpts_by_gw") or [] if int(item.get("gw") or -1) == planning_gw),
                None,
            )
            if not row:
                continue
            mean = float(row.get("mean") or 0.0)
            cs = row.get("clean_sheet_probability")
            cs_valid = cs is None or 0.0 <= float(cs) <= 1.0
            if mean >= 0.0 and cs_valid and bool(player.get("xmins")):
                good += 1
        return good == len(players), {
            "source": "data/projections.json",
            "planning_gw": planning_gw,
            "sample": len(players),
            "valid": good,
            "recomputed_formula": False,
        }

    def canonical_structural_probe() -> tuple[bool, dict]:
        lock = read_json(CONFIG / "locked_squad.json", {})
        universe = read_json(DATA / "universe.json", {})
        umap = {
            int(player["element"]): player
            for player in universe.get("players") or []
            if player.get("element") is not None
        }
        players = list(lock.get("players") or [])
        expected_counts = {
            key: int(value)
            for key, value in (SQUAD_RULES.get("position_counts") or {}).items()
        }
        expected_size = int(SQUAD_RULES.get("squad_size") or 0)
        max_per_club = int(SQUAD_RULES.get("max_players_per_club") or 0)
        counts = Counter(str(player.get("position") or "") for player in players)
        ids = [int(player.get("element") or -1) for player in players]
        clubs = Counter()
        missing_identity = []
        for element in ids:
            source = umap.get(element)
            if not source:
                missing_identity.append(element)
                continue
            clubs[int(source.get("team_id") or -1)] += 1
        actual_counts = {key: int(counts.get(key, 0)) for key in expected_counts}
        valid = (
            len(players) == expected_size
            and len(ids) == len(set(ids))
            and not missing_identity
            and actual_counts == expected_counts
            and max(clubs.values(), default=0) <= max_per_club
        )
        return valid, {
            "source": "config/locked_squad.json + data/universe.json + src.rules.SQUAD_RULES",
            "players": len(players),
            "expected": expected_size,
            "position_counts": actual_counts,
            "max_club_count": max(clubs.values(), default=0),
            "missing_identity": missing_identity,
            "recomputed_optimizer_logic": False,
        }

    audit_engine._probe_xmins = canonical_xmins_probe
    audit_engine._probe_projection = canonical_projection_probe
    audit_engine._probe_structural = canonical_structural_probe
    return ("xmins", "projection", "structural")


def _publish_gate0_registry_contract(expected: dict[str, int]) -> None:
    """Expose Gate0 expected/declared metadata consistently with DSS groups."""
    registry = json.loads(audit_engine.REGISTRIES["gate0"].read_text(encoding="utf-8"))
    declared = len(registry.get("checks") or [])
    expected_count = int(expected["gate0"])
    for path in (audit_engine.PRE_OUT, audit_engine.OUT):
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        gate0 = dict(payload.get("gate0") or {})
        gate0["expected"] = expected_count
        gate0["declared"] = declared
        payload["gate0"] = gate0
        audit_engine.atomic_json(path, payload)


def _optional_auth_health() -> dict:
    auth = read_json(DATA / "auth.json", {})
    if not isinstance(auth, dict) or not auth:
        return {
            "class": "OPTIONAL_PRIVATE_ENRICHMENT",
            "required": False,
            "ready": False,
            "status": "UNAVAILABLE",
            "state": "SERVICE_UNAVAILABLE",
            "decision_blocking": False,
            "reasons": ["auth_artifact_unavailable"],
            "finance": {
                "exact_private": False,
                "provenance": "PUBLIC_RECONSTRUCTION_NON_EXACT",
            },
        }

    reported = auth.get("enhancement_health") or auth.get("production_readiness") or {}
    finance = auth.get("safe_finance") or {}
    exact_private = (
        auth.get("state") == "VALID"
        and auth.get("verified_entry") == auth.get("expected_entry")
        and finance.get("private_exact_sell_total") is not None
        and finance.get("private_exact_purchase_total") is not None
    )
    return {
        "class": "OPTIONAL_PRIVATE_ENRICHMENT",
        "required": False,
        "ready": bool(reported.get("ready")),
        "status": str(reported.get("status") or "DEGRADED"),
        "state": auth.get("state"),
        "decision_blocking": False,
        "reasons": list(reported.get("reasons") or []),
        "finance": {
            "exact_private": exact_private,
            "provenance": "AUTHENTICATED_OFFICIAL" if exact_private else "PUBLIC_RECONSTRUCTION_NON_EXACT",
        },
    }


def _publish_optional_private_enrichment_health() -> None:
    health = _optional_auth_health()
    for path in (audit_engine.PRE_OUT, audit_engine.OUT):
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["service_classes"] = {
            "REQUIRED_CORE": {"failure_policy": "FAIL_CLOSED", "decision_blocking": True},
            "OPTIONAL_PRIVATE_ENRICHMENT": {"failure_policy": "FAIL_SOFT", "decision_blocking": False},
        }
        payload["optional_private_enrichment"] = {"authenticated_official": health}
        audit_engine.atomic_json(path, payload)


def _weather_context_health() -> dict:
    health = read_json(DATA / "weather_context_health.json", {})
    allowed = {"PASS", "PARTIAL", "STALE", "UNAVAILABLE"}
    status = str(health.get("status") or "UNAVAILABLE")
    if status not in allowed:
        status = "UNAVAILABLE"
    return {
        "status": status,
        "allowed_statuses": sorted(allowed),
        "fixture_count": int(health.get("fixture_count") or 0),
        "available_count": int(health.get("available_count") or 0),
        "stale_count": int(health.get("stale_count") or 0),
        "unavailable_count": int(health.get("unavailable_count") or 0),
        "decision_blocking": False,
        "tactical_context_complete": status == "PASS",
        "reasons": list(health.get("reasons") or (["weather_context_health_unavailable"] if not health else [])),
    }


def _publish_weather_context_health() -> None:
    weather = _weather_context_health()
    for path in (audit_engine.PRE_OUT, audit_engine.OUT):
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["weather_context"] = weather
        payload["tactical_context_completeness"] = {
            "status": "COMPLETE" if weather["tactical_context_complete"] else "INCOMPLETE",
            "complete": bool(weather["tactical_context_complete"]),
            "weather_status": weather["status"],
            "rule": "COMPLETE_REQUIRES_WEATHER_CONTEXT_PASS",
        }
        audit_engine.atomic_json(path, payload)


def run() -> None:
    expected = activate_registry_contract()
    activate_freshness_contract()
    activate_canonical_probe_contracts()
    audit_engine.run()
    _publish_gate0_registry_contract(expected)
    _publish_optional_private_enrichment_health()
    _publish_weather_context_health()


if __name__ == "__main__":
    run()
