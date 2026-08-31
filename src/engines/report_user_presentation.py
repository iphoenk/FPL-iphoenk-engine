from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from src.utils import DATA, ROOT, atomic_json, read_json

REPORTING_CONFIG = ROOT / "config" / "intelligence" / "reporting.json"
REPORT_STATE = DATA / "report_state.json"
LATEST = DATA / "latest.json"

RAW_DECISION_TOKENS = ("HOLD", "CHANGE", "REVIEW", "LOCK", "LEAN", "OPEN")
COMPLETED_CHECKPOINT_STATUSES = {"COMPLETED", "LATE_RECOVERED"}


@lru_cache(maxsize=1)
def load_reporting_policy() -> dict[str, Any]:
    return json.loads(REPORTING_CONFIG.read_text(encoding="utf-8"))


def _parse_hhmm(value: str) -> tuple[int, int]:
    hour_text, minute_text = value.split(":", 1)
    hour, minute = int(hour_text), int(minute_text)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid checkpoint time: {value}")
    return hour, minute


def _checkpoint_policy(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = (policy or load_reporting_policy()).get("scheduled_report_checkpoints") or {}
    if not cfg.get("enabled", False):
        return {"enabled": False, "timezone": "Asia/Jakarta", "slots": [], "grace_minutes": 60, "history_days": 14}
    slots = list(cfg.get("slots") or [])
    ids = [str(row.get("id") or "") for row in slots]
    if not slots or any(not value for value in ids) or len(ids) != len(set(ids)):
        raise RuntimeError("scheduled report checkpoints require unique non-empty slot ids")
    for row in slots:
        _parse_hhmm(str(row.get("time") or ""))
    return cfg


def _recovery_ids(value: str | None = None) -> set[str]:
    raw = value if value is not None else os.getenv("FPL_RECOVERY_CHECKPOINT_IDS", "")
    return {item.strip() for item in str(raw or "").split(",") if item.strip()}


def _operational_health(checkpoint: dict[str, Any], engine_state: str | None) -> dict[str, Any]:
    missed = list(checkpoint.get("missed_due") or [])
    recovered = list(checkpoint.get("recovered_late") or [])
    checkpoint_health = "RED" if missed else "AMBER" if recovered else "GREEN"
    engine = str(engine_state or "UNKNOWN").upper()
    if checkpoint_health == "RED" or engine == "RED":
        overall = "RED"
    elif checkpoint_health == "AMBER" or engine in {"AMBER", "YELLOW", "DEGRADED"}:
        overall = "AMBER"
    elif engine == "GREEN":
        overall = "GREEN"
    else:
        overall = engine
    return {
        "overall": overall,
        "engine": engine,
        "checkpoint": checkpoint_health,
        "missed_checkpoint_ids": [str(row.get("id")) for row in missed],
        "late_recovered_checkpoint_ids": [str(row.get("id")) for row in recovered],
        "checkpoint_completeness": checkpoint.get("completeness"),
    }


def resolve_report_checkpoint(
    now_utc: datetime,
    state: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    recovered_slot_ids: set[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    cfg = _checkpoint_policy(policy)
    current_state = dict(state or {})
    history = [dict(row) for row in current_state.get("checkpoint_history") or [] if isinstance(row, dict)]
    recovery_ids = set(recovered_slot_ids or set())
    if not cfg.get("enabled"):
        checkpoint = {
            "schema": "report_checkpoint.v1",
            "enabled": False,
            "current": {"kind": "ROUTINE", "label": "Report rutin"},
            "completeness": "NOT_APPLICABLE",
            "missed_due": [],
            "recovered_late": [],
        }
        return checkpoint, current_state

    tz = ZoneInfo(str(cfg.get("timezone") or "Asia/Jakarta"))
    now = now_utc.astimezone(timezone.utc)
    local_now = now.astimezone(tz)
    local_date = local_now.date().isoformat()
    grace = timedelta(minutes=max(1, int(cfg.get("grace_minutes") or 60)))
    retain_days = max(1, int(cfg.get("history_days") or 14))
    cutoff = (local_now.date() - timedelta(days=retain_days)).isoformat()
    history = [row for row in history if str(row.get("local_date") or "") >= cutoff]

    completed_records = {
        str(row.get("slot_id")): row
        for row in history
        if row.get("local_date") == local_date and str(row.get("status") or "") in COMPLETED_CHECKPOINT_STATUSES
    }
    completed_today = set(completed_records)
    slots_today: list[dict[str, Any]] = []
    for row in cfg.get("slots") or []:
        hour, minute = _parse_hhmm(str(row.get("time")))
        scheduled = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        slots_today.append({
            "id": str(row.get("id")),
            "label": str(row.get("label") or row.get("id")),
            "scheduled": scheduled,
        })
    slots_today.sort(key=lambda row: row["scheduled"])

    current_slot: dict[str, Any] | None = None
    missed_due: list[dict[str, Any]] = []
    recovered_late: list[dict[str, Any]] = []
    newly_recovered_late: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    for row in slots_today:
        slot_id = row["id"]
        scheduled = row["scheduled"]
        completed = slot_id in completed_today
        if completed:
            completed_record = completed_records.get(slot_id) or {}
            previous_status = str(completed_record.get("status") or "COMPLETED")
            state_label = "LATE_RECOVERED" if previous_status == "LATE_RECOVERED" else "COMPLETED"
            if previous_status == "LATE_RECOVERED":
                recovered_late.append({
                    "id": slot_id,
                    "label": row["label"],
                    "scheduled_local": str(completed_record.get("scheduled_local") or scheduled.isoformat()),
                    "recovered_local": str(completed_record.get("generated_local") or ""),
                })
        elif local_now < scheduled:
            state_label = "PENDING"
        elif local_now <= scheduled + grace:
            state_label = "DUE"
            if current_slot is None:
                current_slot = row
        elif slot_id in recovery_ids:
            entry = {
                "slot_id": slot_id,
                "label": row["label"],
                "local_date": local_date,
                "scheduled_local": scheduled.isoformat(),
                "generated_at_utc": now.isoformat(),
                "generated_local": local_now.isoformat(),
                "status": "LATE_RECOVERED",
                "timeliness": "LATE_RECOVERED",
            }
            history.append(entry)
            completed_today.add(slot_id)
            completed_records[slot_id] = entry
            state_label = "LATE_RECOVERED"
            recovered_summary = {
                "id": slot_id,
                "label": row["label"],
                "scheduled_local": scheduled.isoformat(),
                "recovered_local": local_now.isoformat(),
            }
            recovered_late.append(recovered_summary)
            newly_recovered_late.append(recovered_summary)
        else:
            state_label = "MISSED"
            missed_due.append({
                "id": slot_id,
                "label": row["label"],
                "scheduled_local": scheduled.isoformat(),
            })
        timeline.append({
            "id": slot_id,
            "label": row["label"],
            "scheduled_local": scheduled.isoformat(),
            "state": state_label,
        })

    if current_slot is not None:
        slot_id = current_slot["id"]
        scheduled = current_slot["scheduled"]
        if slot_id not in completed_today:
            entry = {
                "slot_id": slot_id,
                "label": current_slot["label"],
                "local_date": local_date,
                "scheduled_local": scheduled.isoformat(),
                "generated_at_utc": now.isoformat(),
                "generated_local": local_now.isoformat(),
                "status": "COMPLETED",
                "timeliness": "ON_TIME_WINDOW",
            }
            history.append(entry)
            completed_today.add(slot_id)
            for item in timeline:
                if item["id"] == slot_id:
                    item["state"] = "COMPLETED"
                    break
        current = {
            "kind": "SCHEDULED_CHECKPOINT",
            "id": slot_id,
            "label": current_slot["label"],
            "scheduled_local": scheduled.isoformat(),
            "generated_local": local_now.isoformat(),
            "timeliness": "ON_TIME_WINDOW",
        }
    elif newly_recovered_late:
        recovered = newly_recovered_late[-1]
        current = {
            "kind": "RECOVERED_CHECKPOINT",
            "id": recovered["id"],
            "label": recovered["label"],
            "scheduled_local": recovered["scheduled_local"],
            "generated_local": local_now.isoformat(),
            "timeliness": "LATE_RECOVERED",
            "recovered_checkpoint_ids": [row["id"] for row in newly_recovered_late],
        }
    else:
        current = {
            "kind": "ROUTINE",
            "label": "Report rutin di luar checkpoint utama",
            "generated_local": local_now.isoformat(),
        }

    checkpoint = {
        "schema": "report_checkpoint.v1",
        "enabled": True,
        "timezone": str(tz),
        "current": current,
        "completeness": "ATTENTION_REQUIRED" if missed_due else "RECOVERED" if recovered_late else "OK",
        "missed_due": missed_due,
        "recovered_late": recovered_late,
        "today": timeline,
        "silent_missing_forbidden": bool(cfg.get("silent_missing_forbidden", True)),
    }
    current_state["checkpoint_history"] = history[-100:]
    current_state["last_checkpoint"] = checkpoint
    return checkpoint, current_state


def _captain_name(payload: dict[str, Any], planning: dict[str, Any]) -> tuple[str | None, str | None]:
    cap = (planning.get("captain") or {}).get("name")
    vice = (planning.get("vice_captain") or {}).get("name")
    section = payload.get("captaincy") or {}
    model = section.get("model") or {}
    if not cap:
        raw = section.get("captain")
        cap = raw if isinstance(raw, str) else (model.get("captain") or {}).get("name") or (section.get("facts") or {}).get("model_candidate")
    if not vice:
        raw = section.get("vice")
        vice = raw if isinstance(raw, str) else (model.get("vice") or {}).get("name") or (section.get("facts") or {}).get("vice_candidate")
    return cap, vice


def _decision_text(value: str | None, *, subject: str, name: str | None = None) -> str:
    state = str(value or "").upper()
    if subject == "squad":
        return {
            "HOLD": "Belum ada alasan kuat untuk mengubah komposisi skuad saat ini.",
            "CHANGE": "Ada perubahan skuad yang layak dipertimbangkan berdasarkan evidence terbaru.",
            "REVIEW": "Komposisi skuad masih perlu ditinjau sebelum keputusan final.",
        }.get(state, "Status komposisi skuad sedang diperbarui.")
    if subject == "xi":
        return {
            "LOCK": "Susunan XI saat ini sudah cukup kuat untuk dipertahankan.",
            "OPEN": "Susunan XI masih terbuka karena perbedaan kandidat starter dan bench belum cukup tegas.",
            "LEAN": "Susunan XI saat ini lebih condong ke pilihan engine, tetapi belum final.",
        }.get(state, "Susunan XI sedang diperbarui.")
    if subject == "captain":
        candidate = name or "kandidat utama"
        return {
            "LOCK": f"{candidate} saat ini menjadi pilihan kapten yang paling kuat.",
            "LEAN": f"Pilihan kapten saat ini lebih condong ke {candidate}, tetapi belum final.",
            "OPEN": "Pilihan kapten masih terbuka karena evidence belum cukup kuat untuk menetapkan satu kandidat.",
        }.get(state, "Pilihan kapten sedang diperbarui.")
    if subject == "price":
        return {
            "HOLD": "Belum ada tekanan harga pada pemain milik sendiri yang memerlukan tindakan segera.",
            "REVIEW": "Ada pemain milik sendiri yang perlu ditinjau karena risiko perubahan harga.",
        }.get(state, "Sinyal harga sedang diperbarui.")
    return "Status sedang diperbarui."


def build_user_presentation(payload: dict[str, Any], checkpoint: dict[str, Any]) -> dict[str, Any]:
    decision = payload.get("decision") or {}
    context = payload.get("gameweek_context") or {}
    planning = context.get("planning") or {}
    historical = list(context.get("historical") or [])
    overall = str(decision.get("overall") or "").upper()
    headline = {
        "HOLD": "Belum ada alasan kuat untuk mengubah skuad.",
        "CHANGE": "Ada perubahan skuad yang layak dipertimbangkan.",
        "REVIEW": "Belum semua keputusan siap difinalkan.",
    }.get(overall, "Status tim sedang diperbarui.")

    cap_name, vice_name = _captain_name(payload, planning)
    active_chip = str(planning.get("active_chip") or "").upper()
    chip_raw = str(decision.get("chip") or "").upper()
    if chip_raw == "REVIEW":
        chip_text = "Status chip perlu ditinjau karena ada ketidaksesuaian aturan atau konteks penggunaan."
    elif active_chip == "WILDCARD":
        chip_text = "Wildcard sedang aktif untuk Gameweek ini. Chip tidak menambah poin langsung; fokusnya adalah kualitas komposisi hasil perubahan skuad."
    elif active_chip == "FREE_HIT":
        chip_text = "Free Hit sedang aktif untuk Gameweek ini dan hanya berlaku untuk komposisi sementara Gameweek tersebut."
    elif active_chip == "BENCH_BOOST":
        chip_text = "Bench Boost sedang aktif, sehingga estimasi poin juga memasukkan kontribusi bench."
    elif active_chip == "TRIPLE_CAPTAIN":
        chip_text = "Triple Captain sedang aktif, sehingga proyeksi memperhitungkan tambahan multiplier kapten."
    else:
        chip_text = "Tidak ada chip aktif yang memerlukan perubahan tindakan saat ini."

    latest_history = max(historical, key=lambda row: int(row.get("gw") or 0), default=None)
    history_text = None
    if latest_history:
        chip_used = str(latest_history.get("chip") or "").replace("_", " ").title()
        suffix = f" dengan chip {chip_used}" if chip_used else ""
        history_text = f"GW{latest_history.get('gw')} selesai dengan {latest_history.get('actual_points')} poin{suffix}."

    estimated = planning.get("estimated_points")
    planning_gw = planning.get("gw") or payload.get("planning_gw")
    estimate_text = (
        f"Estimasi saat ini untuk GW{planning_gw} adalah sekitar {float(estimated):.2f} poin."
        if estimated is not None and planning_gw is not None
        else "Estimasi poin Gameweek berikutnya belum tersedia."
    )
    formation = planning.get("formation")
    xi_text = _decision_text(decision.get("starting_xi"), subject="xi")
    if formation:
        xi_text = f"Formasi yang sedang diproyeksikan {formation}. {xi_text}"

    override_text = None
    if planning.get("user_override_active"):
        comparison = planning.get("comparison") or {}
        delta = comparison.get("user_minus_engine_estimated_points")
        delta_text = f" Selisih estimasi terhadap pilihan engine {float(delta):+.2f} poin." if delta is not None else ""
        override_text = "Keputusan manual pengguna menjadi baseline aktif; rekomendasi engine tetap ditampilkan sebagai pembanding dan tidak menimpa pilihan tersebut." + delta_text
    elif (planning.get("baseline") or {}).get("override_applied"):
        source = (planning.get("baseline") or {}).get("authority_source")
        override_text = "Komposisi planning menggunakan baseline khusus Gameweek ini"
        if source:
            override_text += f" dari {str(source).replace('_', ' ').lower()}"
        override_text += ". Baseline ini tidak boleh terbawa otomatis ke Gameweek berikutnya."

    summary_parts = [part for part in (history_text, estimate_text) if part]
    if checkpoint.get("missed_due"):
        checkpoint_text = "Ada checkpoint terjadwal yang terlewat dan belum berhasil dipulihkan."
    elif checkpoint.get("recovered_late"):
        checkpoint_text = "Checkpoint yang sempat terlewat sudah dipulihkan melalui eksekusi susulan dan dicatat sebagai terlambat."
    else:
        checkpoint_text = "Checkpoint report terjadwal yang sudah jatuh tempo tercatat lengkap."
    presentation = {
        "schema": "user_report_presentation.v1",
        "language": "id-ID",
        "headline": headline,
        "summary": " ".join(summary_parts),
        "squad": _decision_text(decision.get("squad"), subject="squad"),
        "starting_xi": xi_text,
        "captaincy": _decision_text(decision.get("captaincy"), subject="captain", name=cap_name),
        "vice_captain": f"Pilihan wakil kapten saat ini {vice_name}." if vice_name else "Pilihan wakil kapten belum final.",
        "chip": chip_text,
        "price": _decision_text(decision.get("price"), subject="price"),
        "planning_gameweek": planning_gw,
        "estimated_points": estimated,
        "latest_finished_gameweek": history_text,
        "user_override_note": override_text,
        "checkpoint_label": ((checkpoint.get("current") or {}).get("label")),
        "checkpoint_completeness": checkpoint_text,
        "raw_decision_state_available_for_audit": True,
    }
    serialized = json.dumps(presentation, ensure_ascii=False)
    leaked = [token for token in RAW_DECISION_TOKENS if token in serialized]
    if leaked:
        raise RuntimeError(f"raw machine decision leaked into user presentation: {leaked}")
    return presentation


def run(now_utc: datetime | None = None) -> dict[str, Any]:
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    state = read_json(REPORT_STATE, {})
    checkpoint, updated_state = resolve_report_checkpoint(
        now,
        state,
        recovered_slot_ids=_recovery_ids(),
    )
    engine_state = (((updated_state.get("state") or {}).get("critical_health") or {}).get("overall"))
    operational_health = _operational_health(checkpoint, engine_state)
    updated_state["operational_health"] = operational_health

    paths = [DATA / "user_report.json", DATA / "decision_brief.json", DATA / "deep_review_payload.json"]
    result: dict[str, Any] = {}
    for path in paths:
        payload = read_json(path, {})
        payload["report_checkpoint"] = checkpoint
        payload["operational_health"] = operational_health
        payload["user_presentation"] = build_user_presentation(payload, checkpoint)
        atomic_json(path, payload)
        result[path.name] = {
            "presentation": True,
            "checkpoint": (checkpoint.get("current") or {}).get("id") or "ROUTINE",
            "operational_health": operational_health.get("overall"),
        }
    atomic_json(REPORT_STATE, updated_state)

    latest = read_json(LATEST, {})
    latest.setdefault("report_serving", {})["natural_user_presentation"] = True
    latest["report_serving"]["report_checkpoint"] = True
    latest["report_checkpoint"] = checkpoint
    latest["operational_health"] = operational_health
    atomic_json(LATEST, latest)
    return {"checkpoint": checkpoint, "operational_health": operational_health, "artifacts": result}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))