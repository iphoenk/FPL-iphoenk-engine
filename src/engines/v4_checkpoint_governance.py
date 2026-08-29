from __future__ import annotations

import argparse
import json
from datetime import datetime

from src.utils import CONFIG, DATA, atomic_json, parse_dt, read_json, utcnow

OUTFILE = DATA / "checkpoint_decision_v4.json"
ACTIONS = CONFIG / "report_action_registry.json"
LANGUAGE_POLICY = CONFIG / "report_language_policy.json"


def _freshness(latest: dict, now: datetime) -> dict:
    context = latest.get("checkpoint_context") or {}
    maximum = int(context.get("max_snapshot_age_minutes") or 90)
    generated = parse_dt(latest.get("generated_at"))
    if not generated:
        return {"pass": False, "age_minutes": None, "max_age_minutes": maximum, "reason": "generated_at_missing"}
    age = max(0.0, (now - generated).total_seconds() / 60.0)
    return {
        "pass": age <= maximum,
        "age_minutes": round(age, 2),
        "max_age_minutes": maximum,
        "reason": None if age <= maximum else "snapshot_stale",
    }


def _action_definition(action: str, actions: dict) -> dict:
    row = dict((actions.get("actions") or {}).get(action) or {})
    if not row:
        raise RuntimeError(f"report action missing: {action}")
    return row


def _planning_authority(locked: dict, scorecard: dict) -> dict:
    planning = scorecard.get("planning_gw") or {}
    basis = planning.get("squad_basis") or {}
    if basis.get("effective_authority"):
        expected = str(basis["effective_authority"])
        override_applied = bool(basis.get("override_applied"))
        target_gw = basis.get("override_target_gw")
        source = basis.get("authority_source")
        baseline_gw = basis.get("baseline_gw")
        planning_gw = basis.get("planning_gw")
    else:
        override_applied = bool(locked.get("wildcard_active"))
        expected = "LOCKED_PRE_DEADLINE" if override_applied else "OFFICIAL_SUBMITTED"
        target_gw = locked.get("target_gw")
        source = locked.get("authority_source") if override_applied else "OFFICIAL_FPL_PICKS"
        baseline_gw = None
        planning_gw = None
    active_chip = str(planning.get("active_chip") or "NONE").upper()
    wildcard_for_planning = active_chip == "WILDCARD" or (
        override_applied and bool(locked.get("wildcard_active"))
    )
    return {
        "expected_authority": expected,
        "override_applied": override_applied,
        "override_target_gw": target_gw,
        "authority_source": source,
        "baseline_gw": baseline_gw,
        "planning_gw": planning_gw,
        "wildcard_active": wildcard_for_planning,
    }


def _plain_reasoning(
    action: str,
    verdict: str,
    freshness: dict,
    lineup: dict,
    planning_scorecard: dict,
    recommended: dict,
    wildcard_active: bool,
) -> list[str]:
    comparison = planning_scorecard.get("engine_comparison") or {}
    delta = comparison.get("user_minus_engine_xpts")
    reasons: list[str] = []

    if action == "REFRESH_REQUIRED":
        return [
            "Data terakhir sudah terlalu lama untuk dijadikan dasar keputusan saat ini.",
            "Perbarui kondisi pemain, harga, dan informasi tim sebelum melakukan perubahan.",
        ]
    if action == "BLOCKED":
        return [
            "Data atau struktur tim belum konsisten untuk menghasilkan keputusan yang aman.",
            "Jangan mengubah tim sampai sumber masalah sudah diperbaiki dan pemeriksaan ulang selesai.",
        ]
    if action == "SIMULATION_ONLY":
        return ["Hasil ini hanya simulasi dan tidak digunakan sebagai instruksi perubahan tim nyata."]

    if action == "HOLD":
        reasons.append("Struktur tim saat ini masih cukup layak untuk dipertahankan.")
        if verdict == "MATERIAL_UPGRADE" and recommended.get("replacements"):
            reasons.append("Ada paket alternatif yang menarik, tetapi belum cukup kuat untuk memaksa perubahan sekarang.")
        elif verdict == "OPTIONAL_IMPROVEMENT":
            reasons.append("Ada alternatif yang sedikit lebih menarik, tetapi manfaatnya belum cukup besar untuk terburu-buru berubah.")
        else:
            reasons.append("Belum ada peningkatan yang cukup jelas untuk membenarkan perubahan struktur saat ini.")
        if isinstance(delta, (int, float)):
            reasons.append(
                f"Perbedaan proyeksi XI saat ini terhadap alternatif sekitar {abs(float(delta)):.2f} poin, "
                "sehingga masih masuk wilayah keputusan yang bisa dipengaruhi preferensi dan informasi terbaru."
            )
        if str(lineup.get("status") or "").upper() != "FINAL_LOCKED":
            reasons.append("XI, bench, kapten, dan vice-captain masih dapat disesuaikan sampai final review.")
        if wildcard_active:
            reasons.append("Karena Wildcard sedang aktif, fokusnya adalah memilih kombinasi 15 pemain terbaik tanpa mempertimbangkan biaya hit.")
        return reasons

    if action == "REVIEW_REQUIRED":
        return [
            "Ada kandidat perubahan yang layak dibandingkan kembali sebelum keputusan final.",
            "Manfaatnya belum cukup kuat untuk langsung dijalankan tanpa mengecek starter security, team news, dan horizon fixture terbaru.",
        ]

    if action == "GO":
        reasons.append("Perbandingan terbaru menunjukkan paket perubahan yang cukup kuat untuk menjadi pilihan utama.")
        if recommended.get("replacements"):
            reasons.append(
                f"Paket yang disarankan melibatkan {int(recommended['replacements'])} perubahan dan tetap harus dikonfirmasi pada final lock."
            )
        return reasons

    return ["Pertahankan keputusan saat ini sampai informasi berikutnya memberikan alasan yang lebih kuat untuk berubah."]


def _plain_actions(action: str, lineup: dict, wildcard_active: bool) -> list[str]:
    if action == "REFRESH_REQUIRED":
        return ["Refresh data terlebih dahulu.", "Jangan mengeksekusi perubahan sebelum hasil terbaru tersedia."]
    if action == "BLOCKED":
        return ["Perbaiki data atau struktur yang bermasalah.", "Jalankan pemeriksaan ulang sebelum mengambil keputusan."]
    if action == "GO":
        if str(lineup.get("status") or "").upper() == "FINAL_LOCKED":
            return ["Pertahankan final lock kecuali muncul berita material baru."]
        return [
            "Bandingkan paket rekomendasi dengan preferensi user.",
            "Berikan final lock hanya setelah XI, bench, kapten, vice, dan chip dikonfirmasi.",
        ]
    actions = [
        "Pertahankan struktur saat ini.",
        "Pantau team news, starter security, harga, dan challenger sampai checkpoint berikutnya.",
    ]
    if wildcard_active:
        actions.append("Gunakan fleksibilitas Wildcard untuk memperbaiki struktur hanya jika ada peningkatan yang benar-benar material.")
    return actions


def _validate_plain_language(reasoning: list[str], actions: list[str], policy: dict) -> None:
    combined = " ".join([*reasoning, *actions]).lower()
    forbidden = [str(value).lower() for value in policy.get("technical_terms_forbidden_in_primary_reasoning") or []]
    leaking = [value for value in forbidden if value and value in combined]
    if leaking:
        raise RuntimeError(f"technical language leaked into primary report reasoning: {leaking}")


def _emission_contract(context: dict) -> dict:
    """Consume checkpoint policy into a fail-closed, single-visible-report contract."""
    if context.get("post_final_emergency_only") is True:
        raise RuntimeError(
            "legacy post_final_emergency_only is forbidden; checkpoint_policy is the sole timing authority"
        )

    authorized = bool(context.get("visible_output_authorized"))
    duplicate_forbidden = context.get("duplicate_report_forbidden") is not False
    if not duplicate_forbidden:
        raise RuntimeError("checkpoint policy must forbid duplicate visible reports")

    policy_id = str(context.get("policy_id") or "INTERNAL_HOURLY_SILENT")
    full_required = bool(context.get("full_visible_report_required"))
    no_change_required = bool(context.get("no_material_change_must_still_report"))
    if policy_id in {"DEADLINE_MONITOR", "FINAL_DEADLINE_REVIEW"}:
        if not authorized or not full_required or not no_change_required:
            raise RuntimeError(f"deadline report contract incomplete for {policy_id}")

    absorbed = list(context.get("absorbed_policy_ids") or [])
    report_scope = list(dict.fromkeys(context.get("report_scope") or []))
    visible_count = 1 if authorized else 0
    return {
        "status": "VISIBLE_AUTHORIZED" if authorized else "SILENT",
        "authorized": authorized,
        "visible_report_count": visible_count,
        "max_visible_reports": 1,
        "single_consolidated_report": True,
        "duplicate_reports_forbidden": True,
        "policy_id": policy_id,
        "collision_merged": bool(context.get("collision_merged")),
        "absorbed_policy_ids": absorbed,
        "full_report_required": full_required,
        "must_report_when_no_material_change": no_change_required,
        "fresh_source_sweep_required": bool(context.get("fresh_source_sweep_required")),
        "price_radar_required": bool(context.get("price_radar_required")),
        "report_scope": report_scope,
        "suppression_allowed": not (authorized and no_change_required),
    }


def govern_checkpoint(
    latest: dict,
    health: dict,
    sanity: dict,
    lineup: dict,
    locked: dict,
    scorecard: dict | None = None,
    now: datetime | str | None = None,
    actions: dict | None = None,
) -> dict:
    if isinstance(now, str):
        evaluated_at = parse_dt(now)
    else:
        evaluated_at = now
    evaluated_at = evaluated_at or utcnow()
    if evaluated_at.tzinfo is None:
        raise RuntimeError("checkpoint governance now must be timezone-aware")

    actions = actions or read_json(ACTIONS, {})
    language_policy = read_json(LANGUAGE_POLICY, {})
    scorecard = scorecard or {}
    context = dict(latest.get("checkpoint_context") or {})
    emission = _emission_contract(context)
    freshness = _freshness(latest, evaluated_at)
    gate0_pass = (health.get("gate0") or {}).get("pass") is True
    framework_red = health.get("overall") == "RED"
    health_go = health.get("go_allowed") is True
    simulation = context.get("is_simulation") is True
    authority = _planning_authority(locked, scorecard)
    wildcard_active = authority["wildcard_active"]
    expected_authority = authority["expected_authority"]
    authority_ok = latest.get("squad_authority") == expected_authority
    verdict = sanity.get("final_verdict") or "KEEP_15"

    reasons: list[str] = []
    if not gate0_pass:
        reasons.append("GATE0_FAILED")
    if framework_red:
        reasons.append("FRAMEWORK_RED")
    if not authority_ok:
        reasons.append("SQUAD_AUTHORITY_MISMATCH")
    if not freshness["pass"]:
        reasons.append("SNAPSHOT_STALE")
    if simulation:
        reasons.append("SIMULATED_AS_OF")
    if health.get("critical_partial"):
        reasons.append("CRITICAL_FRAMEWORK_PARTIAL")
    if health.get("critical_warmup"):
        reasons.append("CRITICAL_PREDICTION_WARMUP")
    if verdict == "OPTIONAL_IMPROVEMENT":
        reasons.append("OPTIONAL_NOT_AUTOMATIC_GO")

    if not gate0_pass or framework_red or not authority_ok:
        action = "BLOCKED"
    elif not freshness["pass"]:
        action = "REFRESH_REQUIRED"
    elif simulation:
        action = "SIMULATION_ONLY"
    elif not health_go:
        action = "HOLD"
    elif verdict == "MATERIAL_UPGRADE" and (sanity.get("recommended_package") or {}).get("material_eligible") is True:
        action = "GO"
    elif verdict == "OPTIONAL_IMPROVEMENT":
        action = "REVIEW_REQUIRED"
    else:
        action = "HOLD"

    action_definition = _action_definition(action, actions)
    explicit_lineup_lock = str(lineup.get("status") or "").upper() == "FINAL_LOCKED"
    final_review = context.get("is_final_review") is True
    lineup_state = "FINAL_LOCKED" if explicit_lineup_lock else "FINAL_REVIEW_REQUIRED" if final_review else "ADJUSTABLE"
    recommended = sanity.get("recommended_package") or {}
    critical_partial = list(health.get("critical_partial") or [])
    critical_warmup = list(health.get("critical_warmup") or [])
    execution_authorized = action == "GO" and explicit_lineup_lock and not simulation
    if action == "GO" and not explicit_lineup_lock:
        reasons.append("USER_FINAL_LOCK_REQUIRED")

    planning_scorecard = scorecard.get("planning_gw") or {}
    human_reasoning = _plain_reasoning(
        action,
        verdict,
        freshness,
        lineup,
        planning_scorecard,
        recommended,
        wildcard_active,
    )
    human_actions = _plain_actions(action, lineup, wildcard_active)
    _validate_plain_language(human_reasoning, human_actions, language_policy)

    return {
        "schema_version": 496,
        "engine": "v4.9.6-checkpoint-governance-single-report",
        "evaluated_at": evaluated_at.isoformat(),
        "checkpoint_context": context,
        "emission": emission,
        "action_state": action,
        "headline": action_definition.get("headline"),
        "summary": action_definition.get("summary"),
        "structure_action": action_definition.get("structure_action"),
        "human_report": {
            "language_policy": language_policy.get("registry"),
            "audience": language_policy.get("audience", "FPL_MANAGER"),
            "decision": action,
            "headline": action_definition.get("headline"),
            "summary": action_definition.get("summary"),
            "why": human_reasoning,
            "what_to_do": human_actions,
            "technical_terms_suppressed_from_primary_reasoning": True,
            "technical_state_location": language_policy.get("technical_state_location"),
        },
        "squad": {
            "authority": latest.get("squad_authority"),
            "expected_authority": expected_authority,
            "authority_ok": authority_ok,
            "baseline_gw": authority.get("baseline_gw"),
            "planning_gw": authority.get("planning_gw"),
            "planning_override_applied": authority.get("override_applied"),
            "planning_override_target_gw": authority.get("override_target_gw"),
            "authority_source": authority.get("authority_source"),
            "wildcard_active": wildcard_active,
            "locked_players": len(locked.get("players") or []),
            "composition_status": "LOCKED_15" if expected_authority == "LOCKED_PRE_DEADLINE" else "SUBMITTED_OR_CURRENT",
            "hit_recommendation": "NOT_APPLICABLE_WILDCARD_ACTIVE" if wildcard_active else "UNASSESSED",
        },
        "decision": {
            "raw_package_verdict": sanity.get("raw_package_verdict"),
            "governed_verdict": verdict,
            "recommended_replacements": recommended.get("replacements"),
            "recommended_out": [row.get("name") for row in recommended.get("out", [])],
            "recommended_in": [row.get("name") for row in recommended.get("in", [])],
            "material_eligible": recommended.get("material_eligible"),
            "engine_is_advisory": True,
            "user_decision_is_final_authority": True,
            "execution_authorized": execution_authorized,
        },
        "lineup": {
            "status": lineup_state,
            "decision_authority": lineup.get("authority") or lineup.get("decision_authority") or "ENGINE_RECOMMENDATION",
            "formation": lineup.get("formation"),
            "captain": (lineup.get("captain") or {}).get("name"),
            "vice_captain": (lineup.get("vice_captain") or {}).get("name"),
            "active_chip": (lineup.get("chip_context") or {}).get("active_chip"),
            "human_override_active": bool(planning_scorecard.get("human_override_active")),
            "engine_comparison": planning_scorecard.get("engine_comparison") or {},
            "requires_explicit_final_lock": not explicit_lineup_lock,
        },
        "personal_gw_scorecard": {
            "status": scorecard.get("status", "UNAVAILABLE"),
            "previous_gw": scorecard.get("previous_gw") or {"status": "UNAVAILABLE"},
            "planning_gw": planning_scorecard or {"status": "UNAVAILABLE"},
            "headline": scorecard.get("headline") or {},
            "history": scorecard.get("history") or [],
        },
        "readiness": {
            "framework_health": health.get("overall"),
            "pipeline_health": health.get("pipeline_health", health.get("overall")),
            "prediction_health": health.get("prediction_health"),
            "decision_engine": health.get("decision_engine"),
            "capability_coverage": health.get("capability_coverage"),
            "gate0_pass": gate0_pass,
            "health_go_allowed": health_go,
            "freshness": freshness,
            "critical_partial": critical_partial,
            "critical_warmup": critical_warmup,
            "reasons": reasons,
        },
        "report_scope": list(emission.get("report_scope") or []),
        "guardrails": {
            "raw_optimizer_not_authoritative": True,
            "optional_improvement_is_not_automatic_go": True,
            "simulation_never_authorizes_action": True,
            "freshness_failure_blocks_action": True,
            "locked_15_separate_from_lineup_lock": True,
            "wildcard_active_means_no_hit": True,
            "scorecard_is_reporting_only": True,
            "planning_authority_target_gw_aware": True,
            "stale_wildcard_flag_does_not_force_future_lock": True,
            "engine_is_advisory": True,
            "user_decision_is_final_authority": True,
            "go_never_auto_executes_without_user_final_lock": True,
            "primary_report_plain_fpl_language": True,
            "technical_reason_codes_separate_from_human_reasoning": True,
            "checkpoint_policy_is_sole_timing_authority": True,
            "legacy_post_final_emergency_path_forbidden": True,
            "visible_report_count_never_exceeds_one": True,
            "collision_scopes_consumed_from_checkpoint_policy": True,
        },
    }


def run(now: str | None = None) -> dict:
    overlay = read_json(DATA / "effective_plan_v4.json", {})
    effective_plan = overlay.get("effective_plan") or {}
    if overlay.get("status") != "PASS" or not effective_plan:
        raise RuntimeError("effective human planning contract required")
    out = govern_checkpoint(
        read_json(DATA / "latest.json", {}),
        read_json(DATA / "framework_health_v4.json", {}),
        read_json(DATA / "recommendation_sanity_v4.json", {}),
        effective_plan,
        read_json(CONFIG / "locked_squad.json", {}),
        scorecard=read_json(DATA / "gw_scorecard_v4.json", {}),
        now=now,
    )
    atomic_json(OUTFILE, out)
    print(
        json.dumps(
            {
                "checkpoint": (out.get("checkpoint_context") or {}).get("policy_id"),
                "visible_report_count": (out.get("emission") or {}).get("visible_report_count"),
                "action": out.get("action_state"),
                "headline": out.get("headline"),
                "governed_verdict": (out.get("decision") or {}).get("governed_verdict"),
                "decision_authority": (out.get("lineup") or {}).get("decision_authority"),
                "previous_gw": ((out.get("personal_gw_scorecard") or {}).get("headline") or {}).get("previous"),
                "planning_gw": ((out.get("personal_gw_scorecard") or {}).get("headline") or {}).get("planning"),
                "squad_basis": (out.get("squad") or {}).get("authority_source"),
                "human_reason_count": len((out.get("human_report") or {}).get("why") or []),
            },
            ensure_ascii=False,
        )
    )
    return out


def cli() -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("--now", help="Timezone-aware deterministic evaluation time")
    args = parser.parse_args()
    return run(args.now)


if __name__ == "__main__":
    cli()
