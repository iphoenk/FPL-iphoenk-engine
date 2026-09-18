from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .league_prefetch import (
    acquire_manager_picks,
    add_manager_live_totals,
    fetch_all_standings,
    live_state,
    standings_artifact,
)
from .official_fpl_client import OfficialFPLClient
from .personal_prefetch import (
    discover_memberships,
    normalise_submitted_picks,
    normalise_team,
    resolve_priority_leagues,
    verified_auth_entry,
)
from .prefetch_contract import (
    DEFAULT_CONFIG,
    DEFAULT_OUTPUT,
    REPORT_KINDS,
    PrefetchContractError,
    artifact_meta,
    bootstrap_index,
    freshness,
    iso,
    lineage,
    load_consumer_context,
    parse_slot,
    read_json,
    resolve_scope,
    reusable,
    select_gw,
    utc_now,
    write_json,
)
from .security import safe_error


_AUTH_ACTION_BY_STATE = {
    "AUTH_AVAILABLE": "NONE",
    "AUTH_EXPIRED": "RENEW_CREDENTIALS",
    "AUTH_INVALID": "REVIEW_AUTH_CONFIGURATION",
    "AUTH_ENTRY_MISMATCH": "VERIFY_ENTRY_CONFIGURATION",
    "AUTH_UNAVAILABLE": "CONFIGURE_CREDENTIALS",
    "NOT_REQUESTED": "NONE",
}


def _auth_observability(auth_state: Any, *, personal_requested: bool) -> tuple[str, bool, str]:
    if not personal_requested:
        return "NOT_REQUESTED", False, "NONE"
    state = str(auth_state or "AUTH_UNAVAILABLE").strip().upper()
    action = _AUTH_ACTION_BY_STATE.get(state, "REVIEW_AUTH_STATE")
    return state, action != "NONE", action


def _is_auth_control_failure(value: Any) -> bool:
    return str(value or "").upper().startswith("AUTH_")


def _parse_prefetch_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _derived_prefetch_currentness(
    snapshot: dict[str, Any] | None,
    *,
    requested_logical_slot: str,
    observed_at: str | datetime,
    maximum_age_minutes: int,
) -> tuple[float | None, bool, str]:
    if not snapshot:
        return None, False, "MISSING"
    generated = _parse_prefetch_timestamp(snapshot.get("generated_at"))
    if generated is None:
        return None, False, "INVALID"
    requested = parse_slot(requested_logical_slot).astimezone(timezone.utc)
    observed = (
        observed_at.astimezone(timezone.utc)
        if isinstance(observed_at, datetime)
        else parse_slot(str(observed_at)).astimezone(timezone.utc)
    )
    cutoff = max(requested, observed)
    age, fresh = freshness(generated, cutoff, int(maximum_age_minutes))
    return age, fresh, "CURRENT" if fresh else "STALE"


def _canonical_prefetch_scope(scope: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    aliases = {"mini": "mini_league", "league": "mini_league"}
    normalized = tuple(
        aliases.get(str(item).strip(), str(item).strip())
        for item in (scope or ())
        if str(item).strip()
    )
    if len(normalized) != len(set(normalized)):
        raise PrefetchContractError("report-prefetch recovery scope contains duplicates")
    unknown = set(normalized) - {"personal", "mini_league", "live"}
    if unknown:
        raise PrefetchContractError(
            f"unsupported report-prefetch recovery scopes: {sorted(unknown)}"
        )
    return normalized



_CANONICAL_SCOPE_BY_REPORT_KIND = {
    "full_master": ("personal", "mini_league"),
    "match_mode": ("personal", "mini_league", "live"),
    "deadline_review": ("personal", "mini_league"),
    "05:30_price": ("mini_league",),
}


def _required_prefetch_scope(
    report_kind: str,
    scope: tuple[str, ...] | list[str] | None,
) -> tuple[str, ...]:
    if scope:
        return _canonical_prefetch_scope(scope)
    if report_kind == "ad_hoc":
        return ()
    return _canonical_prefetch_scope(_CANONICAL_SCOPE_BY_REPORT_KIND.get(report_kind, ()))


def _snapshot_prefetch_scope(snapshot: dict[str, Any]) -> tuple[str, ...]:
    explicit = snapshot.get("scope")
    if isinstance(explicit, (list, tuple)):
        return _canonical_prefetch_scope(list(explicit))
    return tuple(
        item
        for item, field in (
            ("personal", "personal_requested"),
            ("mini_league", "mini_league_requested"),
            ("live", "live_requested"),
        )
        if snapshot.get(field) is True
    )


def _snapshot_prefetch_identity(snapshot: dict[str, Any]) -> str | None:
    for field in ("report_prefetch_run_id", "request_id", "refresh_identity"):
        value = str(snapshot.get(field) or "").strip()
        if value:
            return value
    return None


def _snapshot_target_slot(snapshot: dict[str, Any]) -> str | None:
    raw = snapshot.get("target_logical_report_slot") or snapshot.get("logical_slot")
    if not raw:
        return None
    return parse_slot(str(raw)).isoformat()


def select_report_prefetch_occurrence(
    latest_snapshot: dict[str, Any] | None,
    *,
    occurrence_snapshots: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    report_kind: str,
    requested_logical_slot: str,
    scope: tuple[str, ...] | list[str] | None = None,
    report_prefetch_identity: str | None = None,
) -> dict[str, Any] | None:
    """Select only a snapshot bound to the exact governed report occurrence.

    latest.json is a convenience pointer, never occurrence authority. A later
    report may replace it, so recovery must match kind + logical slot +
    canonical scope and, when supplied, the concrete prefetch identity.
    """
    if report_kind not in REPORT_KINDS:
        raise PrefetchContractError(f"unsupported report_kind={report_kind}")
    requested_slot = parse_slot(requested_logical_slot).isoformat()
    required_scope = _required_prefetch_scope(report_kind, scope)
    if report_kind == "ad_hoc" and not required_scope:
        raise PrefetchContractError(
            "ad_hoc report-prefetch occurrence selection requires scope"
        )

    explicit_identity = str(report_prefetch_identity or "").strip() or None
    candidates: list[dict[str, Any]] = []
    if isinstance(latest_snapshot, dict):
        candidates.append(latest_snapshot)
    candidates.extend(
        item for item in (occurrence_snapshots or ()) if isinstance(item, dict)
    )

    matches: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str | None, str]] = set()
    for candidate in candidates:
        candidate_kind = str(candidate.get("report_kind") or "").strip()
        if candidate_kind != report_kind:
            continue
        try:
            candidate_slot = _snapshot_target_slot(candidate)
        except PrefetchContractError:
            continue
        if candidate_slot != requested_slot:
            continue
        try:
            candidate_scope = _snapshot_prefetch_scope(candidate)
        except PrefetchContractError:
            continue
        if candidate_scope != required_scope:
            continue
        candidate_identity = _snapshot_prefetch_identity(candidate)
        if explicit_identity is not None and candidate_identity != explicit_identity:
            continue
        generated_raw = str(candidate.get("generated_at") or "")
        dedupe_key = (candidate_identity, candidate_slot, generated_raw)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        matches.append(candidate)

    if not matches:
        return None

    def order_key(candidate: dict[str, Any]) -> tuple[datetime, str]:
        generated = _parse_prefetch_timestamp(candidate.get("generated_at"))
        if generated is None:
            generated = datetime.min.replace(tzinfo=timezone.utc)
        return generated, _snapshot_prefetch_identity(candidate) or ""

    return dict(max(matches, key=order_key))


def evaluate_report_prefetch_readiness(
    snapshot: dict[str, Any] | None,
    *,
    report_kind: str,
    requested_logical_slot: str,
    maximum_age_minutes: int,
    refresh_attempt: int = 0,
    max_refresh_attempts: int = 1,
    reason: str = "fpl_master_report_prefetch_recovery",
    scope: tuple[str, ...] | list[str] | None = None,
    observed_at: str | datetime | None = None,
    occurrence_snapshots: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    report_prefetch_identity: str | None = None,
) -> dict[str, Any]:
    """Recompute report-prefetch currentness and plan only the governed existing refresh path.

    Stored `fresh_for_target_report` is observability, never read-time truth. A stale,
    missing or incomplete snapshot may request the existing issue #431
    `/v6-report-prefetch` transport; this function never edits the core scheduler
    title, creates a cron, or marks a core operational slot complete.
    """
    if report_kind not in REPORT_KINDS:
        raise PrefetchContractError(f"unsupported report_kind={report_kind}")
    if refresh_attempt < 0 or max_refresh_attempts < 1:
        raise PrefetchContractError("report-prefetch recovery attempt bounds are invalid")
    requested = parse_slot(requested_logical_slot)
    observed = observed_at or requested
    scopes = _required_prefetch_scope(report_kind, scope)
    if report_kind == "ad_hoc" and not scopes:
        raise PrefetchContractError("ad_hoc report-prefetch recovery requires scope")

    selected = select_report_prefetch_occurrence(
        snapshot,
        occurrence_snapshots=occurrence_snapshots,
        report_kind=report_kind,
        requested_logical_slot=requested.isoformat(),
        scope=scopes,
        report_prefetch_identity=report_prefetch_identity,
    )
    selection_source = "MISSING"
    if selected is not None:
        latest_identity = _snapshot_prefetch_identity(snapshot or {})
        selected_identity = _snapshot_prefetch_identity(selected)
        try:
            latest_target = _snapshot_target_slot(snapshot or {})
        except PrefetchContractError:
            latest_target = None
        selection_source = (
            "LATEST"
            if latest_target == requested.isoformat()
            and latest_identity == selected_identity
            else "EXACT_OCCURRENCE_HISTORY"
        )

    age, fresh, freshness_status = _derived_prefetch_currentness(
        selected,
        requested_logical_slot=requested.isoformat(),
        observed_at=observed,
        maximum_age_minutes=maximum_age_minutes,
    )
    complete = bool(
        selected
        and selected.get("public_core_complete", selected.get("complete")) is True
    )
    snapshot_kind = str((selected or {}).get("report_kind") or "").strip()
    kind_match = bool(selected and snapshot_kind == report_kind)
    target_match = bool(
        selected and _snapshot_target_slot(selected) == requested.isoformat()
    )
    scope_match = bool(
        selected and _snapshot_prefetch_scope(selected) == scopes
    )

    if selected is None and snapshot is not None:
        freshness_status = "MISMATCH"
    if freshness_status == "CURRENT" and not complete:
        freshness_status = "INCOMPLETE"
    if freshness_status == "CURRENT" and not (kind_match and target_match and scope_match):
        freshness_status = "MISMATCH"

    ready = bool(
        fresh
        and complete
        and kind_match
        and target_match
        and scope_match
    )
    refresh_required = bool(not ready and refresh_attempt < max_refresh_attempts)
    command = None
    if refresh_required:
        command_parts = [
            "/v6-report-prefetch",
            f"report_kind={report_kind}",
            f"logical_slot={requested.isoformat()}",
        ]
        if report_kind == "ad_hoc":
            command_parts.append(f"scope={','.join(scopes)}")
        audit_reason = str(reason or "").strip()
        if not audit_reason or any(character.isspace() for character in audit_reason):
            raise PrefetchContractError("report-prefetch recovery reason must be one token")
        command_parts.extend([f"reason={audit_reason}", "force=true"])
        command = " ".join(command_parts)

    return {
        "ready": ready,
        "freshness_status": freshness_status,
        "fresh_for_target_report": bool(fresh),
        "stored_fresh_for_target_report": (
            (snapshot or {}).get("fresh_for_target_report")
        ),
        "age_target_minutes": age,
        "public_core_complete": complete,
        "report_kind_match": kind_match,
        "target_logical_slot_match": target_match,
        "scope_match": scope_match,
        "selection_source": selection_source,
        "selected_target_logical_report_slot": (
            _snapshot_target_slot(selected) if selected else None
        ),
        "selected_report_prefetch_run_id": (
            _snapshot_prefetch_identity(selected) if selected else None
        ),
        "requested_logical_slot": requested.isoformat(),
        "refresh_attempt": int(refresh_attempt),
        "max_refresh_attempts": int(max_refresh_attempts),
        "refresh_required": refresh_required,
        "refresh_transport": "ISSUE_431_COMMENT",
        "refresh_command": command,
        "refresh_identity": (
            f"{report_kind}|{requested.isoformat()}|{','.join(scopes)}|{str(reason or '').strip()}"
        ),
        "next_action": (
            "USE_REPORT_PREFETCH"
            if ready
            else "GOVERNED_REPORT_PREFETCH_REFRESH"
            if refresh_required
            else "REPORT_PREFETCH_RECOVERY_EXHAUSTED"
        ),
        "core_schedule_mutation_allowed": False,
        "independent_cron_allowed": False,
    }


_REPORT_SCOPE_GOOD_STATES = frozenset({"GREEN", "PASS", "AVAILABLE", "CURRENT"})
_REPORT_AUTH_FAILURE_STATES = frozenset({"AUTH_EXPIRED", "AUTH_FAILED"})


def normalize_report_auth_state(auth_state: Any, *, requested: bool) -> str:
    """Normalize provider/auth implementation states into the report contract."""
    if not requested:
        return "AUTH_NOT_REQUESTED"
    state = str(auth_state or "").strip().upper()
    if state in {"AUTH_OK", "AUTH_AVAILABLE", "AVAILABLE"}:
        return "AUTH_OK"
    if state == "AUTH_EXPIRED":
        return "AUTH_EXPIRED"
    return "AUTH_FAILED"


def evaluate_report_scope_health(
    scope_status: dict[str, Any],
    *,
    required_scopes: tuple[str, ...] | list[str],
    public_report: bool,
) -> dict[str, Any]:
    """Evaluate health per scope; CORE green can never mask another required scope."""
    normalized = {
        str(scope).strip().upper(): str(status or "UNKNOWN").strip().upper()
        for scope, status in dict(scope_status or {}).items()
    }
    requested_auth = normalized.get("AUTH") not in {None, "", "NOT_REQUESTED", "AUTH_NOT_REQUESTED"}
    auth_state = normalize_report_auth_state(
        normalized.get("AUTH"),
        requested=requested_auth,
    )
    normalized["AUTH"] = auth_state

    required = tuple(dict.fromkeys(str(scope).strip().upper() for scope in required_scopes))
    blocking: list[str] = []
    for scope in required:
        state = normalized.get(scope, "MISSING")
        if scope == "AUTH":
            if public_report:
                continue
            if state != "AUTH_OK":
                blocking.append(scope)
            continue
        if state not in _REPORT_SCOPE_GOOD_STATES:
            blocking.append(scope)

    return {
        "scope_status": normalized,
        "required_scopes": list(required),
        "blocking_scopes": blocking,
        "overall_status": "GREEN" if not blocking else "AMBER",
        "auth_state": auth_state,
        "auth_blocks_public_report": bool(public_report is False and "AUTH" in blocking),
        "core_green_implies_report_green": False,
    }


def build_report_scope_lineage(
    scope_records: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    logical_slot: str,
    observed_at: str | datetime,
    maximum_age_minutes: int,
) -> dict[str, Any]:
    """Build report lineage and fail closed on mixed core/prefetch generations."""
    slot = parse_slot(logical_slot)
    observed = (
        observed_at
        if isinstance(observed_at, datetime)
        else parse_slot(str(observed_at))
    )
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise PrefetchContractError("report lineage observed_at must be timezone-aware")

    parsed_rows: list[tuple[datetime, str, dict[str, Any]]] = []
    for raw in scope_records or ():
        generated_raw = str(raw.get("generated_at") or "").strip()
        generated = _parse_prefetch_timestamp(generated_raw)
        if generated is None:
            continue
        parsed_rows.append((generated, generated_raw, dict(raw)))

    if not parsed_rows:
        return {
            "min_generated_at": None,
            "age_minutes": None,
            "source_run_id": None,
            "report_prefetch_run_id": None,
            "logical_slot": slot.isoformat(),
            "freshness_status": "MISSING",
            "generation_coherent": False,
            "cross_generation_mix_blocked": False,
            "usable": False,
        }

    oldest_utc, oldest_raw, _ = min(parsed_rows, key=lambda row: row[0])
    cutoff = max(slot.astimezone(timezone.utc), observed.astimezone(timezone.utc))
    age_minutes = round(max(0.0, (cutoff - oldest_utc).total_seconds() / 60.0), 3)

    source_run_ids = {
        str(row.get("source_run_id")).strip()
        for _, _, row in parsed_rows
        if str(row.get("source_run_id") or "").strip()
    }
    prefetch_run_ids = {
        str(row.get("report_prefetch_run_id")).strip()
        for _, _, row in parsed_rows
        if str(row.get("report_prefetch_run_id") or "").strip()
    }
    coherent = len(source_run_ids) <= 1 and len(prefetch_run_ids) <= 1
    fresh = age_minutes <= int(maximum_age_minutes)
    if not coherent:
        freshness_status = "CROSS_GENERATION"
    else:
        freshness_status = "CURRENT" if fresh else "STALE"

    return {
        "min_generated_at": oldest_raw,
        "age_minutes": age_minutes,
        "source_run_id": next(iter(source_run_ids), None),
        "report_prefetch_run_id": next(iter(prefetch_run_ids), None),
        "logical_slot": slot.isoformat(),
        "freshness_status": freshness_status,
        "generation_coherent": coherent,
        "cross_generation_mix_blocked": not coherent,
        "usable": bool(coherent and fresh),
    }


class PrefetchService:
    def __init__(
        self,
        *,
        config: dict[str, Any],
        output_root: Path = DEFAULT_OUTPUT,
        client: Any | None = None,
        now: datetime | None = None,
    ) -> None:
        self.config = config
        self.output_root = output_root
        self.client = client
        self.now = (now or utc_now()).astimezone(timezone.utc)

    def _client(self) -> Any:
        if self.client is None:
            self.client = OfficialFPLClient(
                timeout_seconds=float(self.config.get("http_timeout_seconds", 15)),
                retries=int(self.config.get("http_retries", 2)),
                backoff_seconds=float(self.config.get("http_backoff_seconds", 0.4)),
            )
        return self.client

    def _publish_health(self, manifest: dict[str, Any]) -> None:
        telemetry = manifest.get("telemetry") or {}
        auth_state = manifest.get("auth_state")
        if manifest.get("personal_requested") and not auth_state:
            current_team = read_json(self.output_root / "personal/current_team.json") or {}
            auth_state = current_team.get("auth_state")
        auth_state, auth_action_required, auth_action = _auth_observability(
            auth_state,
            personal_requested=bool(manifest.get("personal_requested")),
        )
        target_slot = str(
            manifest.get("target_logical_report_slot")
            or manifest.get("logical_slot")
            or iso(self.now)
        )
        maximum_age = int(
            manifest.get("prefetch_max_age_minutes")
            or self.config.get("prefetch_max_age_minutes", 35)
        )
        derived_age, derived_fresh, freshness_status = _derived_prefetch_currentness(
            manifest,
            requested_logical_slot=target_slot,
            observed_at=self.now,
            maximum_age_minutes=maximum_age,
        )
        strict_status = (
            "GREEN"
            if manifest.get("complete") and derived_fresh
            else ("AMBER" if manifest.get("source_failures") or not manifest.get("complete") else "STALE")
        )
        public_complete = bool(manifest.get("public_core_complete", manifest.get("complete")))
        public_status = (
            "GREEN"
            if public_complete and derived_fresh
            else ("AMBER" if not public_complete else "STALE")
        )
        health = {
            "schema_version": 2,
            "generated_at": manifest["generated_at"],
            "prefetch_status": strict_status,
            "strict_prefetch_status": strict_status,
            "public_core_status": public_status,
            "public_core_complete": public_complete,
            "authenticated_personal_required_for_public_green": bool(
                manifest.get("authenticated_personal_required_for_public_green")
            ),
            "authenticated_personal_deferred": bool(manifest.get("authenticated_personal_deferred")),
            "personal_status": manifest.get("personal_status"),
            "public_personal_status": manifest.get("public_personal_status"),
            "auth_state": auth_state,
            "auth_action_required": auth_action_required,
            "auth_action": auth_action,
            "league_status": manifest.get("mini_league_status"),
            "live_status": manifest.get("live_status"),
            "expected_managers": manifest.get("expected_manager_count"),
            "collected_managers": manifest.get("collected_manager_count"),
            "cache_hits": telemetry.get("cache_hits", 0),
            "cache_misses": telemetry.get("cache_misses", 0),
            "request_count": telemetry.get("request_count", 0),
            "failed_requests": telemetry.get("failed_requests", 0),
            "duration_ms": telemetry.get("duration_ms", 0),
            "fresh_for_target_report": derived_fresh,
            "stored_fresh_for_target_report": manifest.get("fresh_for_target_report"),
            "freshness_status": freshness_status,
            "age_target_minutes": derived_age,
            "freshness_evaluated_at": iso(self.now),
            "idempotent_reuse": bool((manifest.get("idempotency") or {}).get("reused")),
        }
        write_json(self.output_root / "health/report_prefetch.json", health)

    def run(
        self,
        *,
        report_kind: str,
        logical_slot: str,
        requested_by: str = "FPL_MASTER_MONITOR",
        requested_for_report: str | None = None,
        ad_hoc_personal: bool = False,
        ad_hoc_mini_league: bool = False,
        ad_hoc_live: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        slot = parse_slot(logical_slot)
        scope = resolve_scope(
            report_kind,
            self.config,
            ad_hoc_personal=ad_hoc_personal,
            ad_hoc_mini_league=ad_hoc_mini_league,
            ad_hoc_live=ad_hoc_live,
        )
        season = str(self.config.get("season") or "UNKNOWN")
        entry_id = int(self.config["entry_id"])
        max_age = int(self.config["prefetch_max_age_minutes"])
        slot_identity = f"{season}|{report_kind}|{slot.isoformat()}"
        prior = read_json(self.output_root / "report_prefetch/latest.json")
        if not force and reusable(
            prior,
            slot_identity=slot_identity,
            logical_slot=slot,
            now=self.now,
            maximum_age_minutes=max_age,
        ):
            result = dict(prior)
            result["idempotency"] = {
                "reused": True,
                "reason": "AUTHORITATIVE_COMPLETE_SLOT_ALREADY_EXISTS",
                "reused_at": iso(self.now),
            }
            result["reuse_telemetry"] = {
                "request_count": 0,
                "failed_requests": 0,
                "duration_ms": round((time.perf_counter() - started) * 1000),
            }
            write_json(self.output_root / "report_prefetch/latest.json", result)
            self._publish_health(result)
            return result

        requested_for_report = requested_for_report or report_kind
        generated_at = iso(self.now)
        source_failures: list[dict[str, Any]] = []
        control_failures: list[str] = []
        artifacts: list[dict[str, Any]] = []
        cache_hits = cache_misses = max_rival_concurrency = 0
        client = self._client() if (scope.personal or scope.mini_league or scope.live) else None
        secrets = tuple(getattr(client, "secret_values", ()) or ()) if client else ()

        bootstrap_result = client.bootstrap() if client else None
        if bootstrap_result and bootstrap_result.get("status") == "LIVE":
            bootstrap_payload = bootstrap_result.get("payload") or {}
            elements = bootstrap_index(bootstrap_payload)
            gw, deadline_passed, deadline_time = select_gw(bootstrap_payload, self.now)
        else:
            bootstrap_payload, elements = {}, {}
            gw, deadline_passed, deadline_time = None, None, None
            if client:
                source_failures.append(
                    {
                        "domain": "official_fpl",
                        "endpoint_class": "bootstrap_static",
                        "status": (bootstrap_result or {}).get("status", "UNAVAILABLE"),
                    }
                )

        entry_result = client.entry(entry_id) if client and (scope.personal or scope.mini_league) else None
        entry_payload = (
            entry_result.get("payload")
            if entry_result and entry_result.get("status") == "LIVE"
            else None
        )
        memberships = discover_memberships(entry_payload or {}, generated_at) if entry_payload else []
        priorities = resolve_priority_leagues(
            memberships, list(self.config.get("priority_leagues") or [])
        ) if entry_payload else []
        if entry_result:
            membership_artifact = {
                "schema_version": 1,
                "entry_id": entry_id,
                "generated_at": generated_at,
                "status": "AVAILABLE" if entry_payload is not None else "UNAVAILABLE",
                "memberships": memberships,
                "priority_resolution": priorities,
                "lineage": lineage(entry_result, entry_id=entry_id),
                "authority": "OFFICIAL_FPL",
            }
            write_json(
                self.output_root / "personal/memberships.json",
                membership_artifact,
                secrets=secrets,
            )
            artifacts.append(artifact_meta(self.output_root, "personal/memberships.json"))
            if entry_result.get("status") != "LIVE":
                source_failures.append(
                    {
                        "domain": "official_fpl_personal",
                        "endpoint_class": "entry",
                        "status": entry_result.get("status"),
                    }
                )

        personal_status = "NOT_REQUESTED"
        public_personal_status = "NOT_REQUESTED"
        personal_auth_state = "NOT_REQUESTED"
        submitted: dict[str, Any] = {}
        if scope.personal:
            picks_result = client.submitted_picks(entry_id, gw) if gw is not None else None
            submitted = normalise_submitted_picks(entry_id, gw, picks_result)
            write_json(
                self.output_root / "personal/submitted_picks.json", submitted, secrets=secrets
            )
            artifacts.append(artifact_meta(self.output_root, "personal/submitted_picks.json"))
            if submitted["status"] != "AVAILABLE":
                source_failures.append(
                    {
                        "domain": "official_fpl_personal",
                        "endpoint_class": "submitted_picks",
                        "status": submitted["status"],
                    }
                )

            auth_state = "AUTH_UNAVAILABLE"
            auth_lineages = []
            my_team_payload = None
            if getattr(client, "auth_configuration_state", "UNAVAILABLE") == "INVALID":
                source_failures.append(
                    {
                        "domain": "official_fpl_personal",
                        "endpoint_class": "authentication",
                        "status": "AUTH_CONFIGURATION_INVALID",
                    }
                )
            elif getattr(client, "auth_available", False):
                me = client.me()
                auth_lineages.append(lineage(me, entry_id=entry_id))
                if me.get("status") == "LIVE":
                    verified = verified_auth_entry(me.get("payload") or {})
                    if verified == entry_id:
                        team = client.my_team(entry_id)
                        auth_lineages.append(lineage(team, entry_id=entry_id))
                        if team.get("status") == "LIVE":
                            auth_state = "AVAILABLE"
                            my_team_payload = team.get("payload") or {}
                        else:
                            auth_state = "DEGRADED"
                            source_failures.append(
                                {
                                    "domain": "official_fpl_personal",
                                    "endpoint_class": "my_team",
                                    "status": team.get("status"),
                                }
                            )
                    elif verified is None:
                        auth_state = "AUTH_IDENTITY_UNVERIFIED"
                        control_failures.append("AUTH_IDENTITY_UNVERIFIED")
                    else:
                        auth_state = "AUTH_ENTRY_MISMATCH"
                        control_failures.append("AUTH_ENTRY_MISMATCH")
                else:
                    auth_state = "DEGRADED"
                    source_failures.append(
                        {
                            "domain": "official_fpl_personal",
                            "endpoint_class": "me",
                            "status": me.get("status"),
                        }
                    )

            team_artifact = normalise_team(
                entry_id=entry_id,
                gw=gw,
                element_index=elements,
                bootstrap_lineage=lineage(bootstrap_result, gw=gw),
                submitted=submitted,
                auth_state=auth_state,
                my_team_payload=my_team_payload,
                auth_lineage=auth_lineages,
                generated_at=generated_at,
            )
            personal_auth_state = str(team_artifact.get("auth_state") or "AUTH_UNAVAILABLE")
            write_json(
                self.output_root / "personal/current_team.json", team_artifact, secrets=secrets
            )
            artifacts.append(artifact_meta(self.output_root, "personal/current_team.json"))
            personal_status = (
                "AVAILABLE"
                if submitted["status"] == "AVAILABLE" and auth_state == "AVAILABLE"
                else ("DEGRADED" if submitted["status"] == "AVAILABLE" else "UNAVAILABLE")
            )
            public_personal_status = (
                "AVAILABLE"
                if submitted["status"] == "AVAILABLE"
                and bootstrap_result is not None
                and bootstrap_result.get("status") == "LIVE"
                else "UNAVAILABLE"
            )

        live_status = "NOT_REQUESTED"
        live_points = None
        live_artifact = None
        live_checked_at = None
        if scope.live:
            if gw is None:
                live_status = "UNAVAILABLE"
                source_failures.append(
                    {"domain": "official_fpl", "endpoint_class": "event_live", "status": "GW_UNRESOLVED"}
                )
            else:
                live_result = client.event_live(gw)
                live_points, live_artifact = live_state(live_result, gw)
                live_status = live_artifact["status"]
                live_checked_at = live_artifact.get("checked_at")
                if live_status != "AVAILABLE":
                    source_failures.append(
                        {
                            "domain": "official_fpl",
                            "endpoint_class": "event_live",
                            "status": live_result.get("status"),
                        }
                    )

        mini_status = "NOT_REQUESTED"
        processed_leagues = []
        primary_id = primary_name = None
        primary_expected = primary_collected = primary_available = primary_missing = None
        primary_cache_complete = None
        standings_checked_at = None

        if scope.mini_league:
            if not entry_payload:
                mini_status = "UNAVAILABLE"
            elif not priorities:
                mini_status = "NOT_CONFIGURED"
                control_failures.append("NO_PRIORITY_LEAGUE_CONFIGURED")
            else:
                states = []
                for priority in priorities:
                    if priority.get("resolution_status") != "RESOLVED":
                        states.append("UNAVAILABLE")
                        control_failures.append(
                            f"PRIORITY_LEAGUE_{priority.get('resolution_status')}:{priority.get('league_kind')}:{priority.get('league_name')}"
                        )
                        processed_leagues.append(
                            {
                                "league_id": None,
                                "league_name": priority.get("league_name"),
                                "league_kind": priority.get("league_kind"),
                                "status": priority.get("resolution_status"),
                            }
                        )
                        continue

                    league_id = int(priority["league_id"])
                    if primary_id is None:
                        primary_id, primary_name = league_id, priority["league_name"]
                    state = fetch_all_standings(client, priority)
                    standings = standings_artifact(
                        league=priority, state=state, entry_id=entry_id, generated_at=generated_at
                    )
                    relative_standings = f"mini_leagues/{league_id}/standings.json"
                    write_json(self.output_root / relative_standings, standings, secrets=secrets)
                    artifacts.append(artifact_meta(self.output_root, relative_standings))
                    if state["lineage"]:
                        standings_checked_at = state["lineage"][-1]["checked_at"]
                    if not state["complete"]:
                        source_failures.append(
                            {
                                "domain": "official_fpl_leagues",
                                "endpoint_class": f"{priority['league_kind']}_standings",
                                "league_id": league_id,
                                "status": "PARTIAL",
                                "failed_pages": state["failed_pages"],
                            }
                        )

                    manager_ids = [int(row["entry_id"]) for row in state["rows"]]
                    manager_picks = None
                    metrics = {"cache_hits": 0, "cache_misses": 0, "maximum_concurrency_used": 0}
                    full_picks = bool(priority.get("full_submitted_picks")) and bool(
                        self.config.get("priority_full_picks_enabled", True)
                    )
                    if state["complete"] and gw is not None and full_picks:
                        picks_relative = f"mini_leagues/{league_id}/gw_{gw}_manager_picks.json"
                        manager_picks, metrics = acquire_manager_picks(
                            client,
                            previous_path=self.output_root / picks_relative,
                            season=season,
                            league_id=league_id,
                            gw=gw,
                            manager_ids=manager_ids,
                            deadline_passed=bool(deadline_passed),
                            workers=int(self.config.get("rival_picks_max_workers", 8)),
                            force=force,
                            cache_enabled=bool(self.config.get("submitted_picks_cache_enabled", True)),
                        )
                        write_json(self.output_root / picks_relative, manager_picks, secrets=secrets)
                        artifacts.append(artifact_meta(self.output_root, picks_relative))
                        cache_hits += metrics["cache_hits"]
                        cache_misses += metrics["cache_misses"]
                        max_rival_concurrency = max(
                            max_rival_concurrency, metrics["maximum_concurrency_used"]
                        )

                    if scope.live and live_artifact is not None:
                        league_live = live_artifact
                        if manager_picks is not None and live_points is not None:
                            league_live = add_manager_live_totals(
                                live_artifact, manager_picks, live_points
                            )
                        live_relative = f"mini_leagues/{league_id}/live_state.json"
                        write_json(self.output_root / live_relative, league_live, secrets=secrets)
                        artifacts.append(artifact_meta(self.output_root, live_relative))

                    league_complete = bool(
                        state["complete"]
                        and (
                            not full_picks
                            or manager_picks is not None and manager_picks.get("complete") is True
                        )
                    )
                    states.append("AVAILABLE" if league_complete else "PARTIAL")
                    processed_leagues.append(
                        {
                            "league_id": league_id,
                            "league_name": priority["league_name"],
                            "league_kind": priority["league_kind"],
                            "status": "AVAILABLE" if league_complete else "PARTIAL",
                            "expected_manager_count": len(manager_ids) if state["complete"] else None,
                            "collected_manager_count": len(manager_ids),
                            "submitted_picks_available_count": manager_picks.get(
                                "submitted_picks_available_count"
                            ) if manager_picks else None,
                            "submitted_picks_missing_count": manager_picks.get(
                                "submitted_picks_missing_count"
                            ) if manager_picks else None,
                            "coverage_percent": manager_picks.get("coverage_percent") if manager_picks else None,
                            "cache_hits": metrics["cache_hits"],
                            "cache_misses": metrics["cache_misses"],
                        }
                    )
                    if league_id == primary_id:
                        primary_expected = len(manager_ids) if state["complete"] else None
                        primary_collected = len(manager_ids)
                        primary_available = manager_picks.get(
                            "submitted_picks_available_count"
                        ) if manager_picks else None
                        primary_missing = manager_picks.get(
                            "submitted_picks_missing_count"
                        ) if manager_picks else None
                        primary_cache_complete = manager_picks.get("complete") if manager_picks else None

                mini_status = (
                    "AVAILABLE"
                    if states and all(state == "AVAILABLE" for state in states)
                    else ("PARTIAL" if any(state in {"AVAILABLE", "PARTIAL"} for state in states) else "UNAVAILABLE")
                )

        if scope.live and live_artifact is not None and not scope.mini_league:
            write_json(
                self.output_root / "report_prefetch/live_state.json",
                live_artifact,
                secrets=secrets,
            )
            artifacts.append(artifact_meta(self.output_root, "report_prefetch/live_state.json"))

        age, fresh = freshness(self.now, slot, max_age)
        telemetry = client.telemetry() if client else {
            "request_count": 0, "failed_requests": 0, "maximum_concurrency_used": 0
        }
        complete = (
            not control_failures
            and (not scope.personal or personal_status == "AVAILABLE")
            and (not scope.mini_league or mini_status == "AVAILABLE")
            and (not scope.live or live_status == "AVAILABLE")
        )
        auth_required_for_public = bool(
            self.config.get("authenticated_personal_required_for_public_green", False)
        )
        public_control_failures = [
            failure
            for failure in control_failures
            if auth_required_for_public or not _is_auth_control_failure(failure)
        ]
        public_core_complete = (
            not public_control_failures
            and (
                not scope.personal
                or (
                    personal_status == "AVAILABLE"
                    if auth_required_for_public
                    else public_personal_status == "AVAILABLE"
                )
            )
            and (not scope.mini_league or mini_status == "AVAILABLE")
            and (not scope.live or live_status == "AVAILABLE")
        )
        personal_auth_state, auth_action_required, auth_action = _auth_observability(
            personal_auth_state,
            personal_requested=scope.personal,
        )
        auth_deferred = bool(
            scope.personal
            and not auth_required_for_public
            and personal_auth_state != "AUTH_AVAILABLE"
        )

        report_prefetch_run_id = str(uuid.uuid4())
        core_manifest = read_json(self.output_root / "manifest.json") or {}
        core_control = dict(core_manifest.get("runtime_control") or {})
        source_run_id = str(
            core_control.get("run_id")
            or core_manifest.get("source_run_id")
            or core_manifest.get("run_id")
            or ""
        ).strip() or None
        core_generated_at = core_manifest.get("generated_at")
        report_auth_state = normalize_report_auth_state(
            personal_auth_state,
            requested=scope.personal,
        )
        scope_health = {
            "CORE": str(core_manifest.get("overall") or "UNKNOWN").upper(),
            "REPORT_PREFETCH": "GREEN" if public_core_complete and fresh else (
                "STALE" if public_core_complete else "DEGRADED"
            ),
            "PERSONAL": personal_status,
            "MINI_LEAGUE": mini_status,
            "AUTH": report_auth_state,
            "ICON+": (
                mini_status
                if primary_name and "ICON+" in str(primary_name).upper()
                else "NOT_REQUESTED"
            ),
        }
        lineage_records: list[dict[str, Any]] = []
        if core_generated_at:
            lineage_records.append(
                {
                    "scope": "CORE",
                    "generated_at": core_generated_at,
                    "source_run_id": source_run_id,
                    "report_prefetch_run_id": None,
                }
            )
        lineage_records.append(
            {
                "scope": "REPORT_PREFETCH",
                "generated_at": generated_at,
                "source_run_id": source_run_id,
                "report_prefetch_run_id": report_prefetch_run_id,
            }
        )
        if scope.personal:
            lineage_records.append(
                {
                    "scope": "PERSONAL",
                    "generated_at": generated_at,
                    "source_run_id": source_run_id,
                    "report_prefetch_run_id": report_prefetch_run_id,
                }
            )
        if scope.mini_league:
            lineage_records.append(
                {
                    "scope": "MINI_LEAGUE",
                    "generated_at": generated_at,
                    "source_run_id": source_run_id,
                    "report_prefetch_run_id": report_prefetch_run_id,
                }
            )
        scope_lineage = build_report_scope_lineage(
            lineage_records,
            logical_slot=slot.isoformat(),
            observed_at=self.now,
            maximum_age_minutes=max_age,
        )

        manifest = {
            "schema_version": 2,
            "request_id": report_prefetch_run_id,
            "report_prefetch_run_id": report_prefetch_run_id,
            "source_run_id": source_run_id,
            "requested_at": generated_at,
            "requested_by": requested_by,
            "requested_for_report": requested_for_report,
            "report_kind": report_kind,
            "target_logical_report_slot": slot.isoformat(),
            "slot_identity": slot_identity,
            "slot_key": f"{season}|{gw if gw is not None else 'GW_UNRESOLVED'}|{report_kind}|{slot.isoformat()}",
            "prefetch_lead_minutes": int(self.config["prefetch_lead_minutes"]),
            "generated_at": generated_at,
            "age_target_minutes": age,
            "prefetch_max_age_minutes": max_age,
            "fresh_for_target_report": fresh,
            "personal_requested": scope.personal,
            "personal_status": personal_status,
            "public_personal_status": public_personal_status,
            "auth_state": personal_auth_state,
            "report_auth_state": report_auth_state,
            "auth_action_required": auth_action_required,
            "auth_action": auth_action,
            "authenticated_personal_required_for_public_green": auth_required_for_public,
            "authenticated_personal_deferred": auth_deferred,
            "mini_league_requested": scope.mini_league,
            "mini_league_status": mini_status,
            "live_requested": scope.live,
            "live_status": live_status,
            "gw": gw,
            "gw_deadline_time": deadline_time,
            "entry_id": entry_id,
            "priority_league_id": primary_id,
            "priority_league_name": primary_name,
            "priority_leagues": processed_leagues,
            "standings_checked_at": standings_checked_at,
            "submitted_picks_cache_gw": gw if primary_id is not None else None,
            "submitted_picks_cache_complete": primary_cache_complete,
            "submitted_picks_manager_count": primary_available,
            "league_manager_count": primary_expected,
            "expected_manager_count": primary_expected,
            "collected_manager_count": primary_collected,
            "submitted_picks_available_count": primary_available,
            "submitted_picks_missing_count": primary_missing,
            "coverage_percent": (
                round(primary_available * 100 / primary_expected, 4)
                if isinstance(primary_available, int)
                and isinstance(primary_expected, int)
                and primary_expected
                else None
            ),
            "live_checked_at": live_checked_at,
            "source_failures": source_failures,
            "control_failures": control_failures,
            "public_control_failures": public_control_failures,
            "scope_health": scope_health,
            "scope_lineage": scope_lineage,
            "cross_generation_mix_blocked": bool(scope_lineage.get("cross_generation_mix_blocked")),
            "telemetry": {
                **telemetry,
                "cache_hits": cache_hits,
                "cache_misses": cache_misses,
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "maximum_concurrency_used": max(
                    int(telemetry.get("maximum_concurrency_used") or 0),
                    max_rival_concurrency,
                ),
            },
            "artifacts": artifacts,
            "complete": complete,
            "strict_complete": complete,
            "public_core_complete": public_core_complete,
            "idempotency": {"reused": False},
            "governance": {
                "data_only": True,
                "decision_authority": "NONE",
                "prediction_authority": "NONE",
                "optimizer_authority": "NONE",
                "independence_group": "official_fpl",
                "core_source_freshness_separate": True,
                "report_prefetch_freshness_separate": True,
                "public_official_fpl_facts_remain_available_without_authenticated_my_team": True,
                "authenticated_personal_state_is_separate_from_public_core_acceptance": True,
                "normal_hourly_personal_refresh": False,
                "price_0530_requires_mini_league_facts": report_kind == "05:30_price",
                "independent_prefetch_cron": False,
            },
        }
        write_json(self.output_root / "report_prefetch/latest.json", manifest, secrets=secrets)
        self._publish_health(manifest)
        return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="V6 governed report-driven FPL prefetch")
    parser.add_argument("--report-kind", required=True, choices=sorted(REPORT_KINDS))
    parser.add_argument("--logical-slot", required=True)
    parser.add_argument("--requested-by", default=os.getenv("V6_PREFETCH_REQUESTED_BY", "FPL_MASTER_MONITOR"))
    parser.add_argument("--requested-for-report")
    parser.add_argument("--personal", action="store_true")
    parser.add_argument("--mini-league", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        manifest = PrefetchService(
            config=load_consumer_context(args.config),
            output_root=args.output_root,
        ).run(
            report_kind=args.report_kind,
            logical_slot=args.logical_slot,
            requested_by=args.requested_by,
            requested_for_report=args.requested_for_report,
            ad_hoc_personal=args.personal,
            ad_hoc_mini_league=args.mini_league,
            ad_hoc_live=args.live,
            force=args.force,
        )
    except PrefetchContractError as exc:
        print(json.dumps({"status": "REJECTED", "error": safe_error(exc)}))
        return 2
    public_complete = bool(manifest.get("public_core_complete", manifest.get("complete")))
    if manifest.get("complete"):
        status = "COMPLETE"
    elif public_complete and manifest.get("authenticated_personal_deferred"):
        status = "PUBLIC_COMPLETE_AUTH_DEFERRED"
    elif public_complete:
        status = "PUBLIC_COMPLETE"
    else:
        status = "PARTIAL"
    print(
        json.dumps(
            {
                "status": status,
                "request_id": manifest.get("request_id"),
                "report_kind": manifest.get("report_kind"),
                "gw": manifest.get("gw"),
                "strict_complete": manifest.get("strict_complete", manifest.get("complete")),
                "public_core_complete": public_complete,
                "personal_status": manifest.get("personal_status"),
                "public_personal_status": manifest.get("public_personal_status"),
                "auth_state": manifest.get("auth_state"),
                "auth_action_required": manifest.get("auth_action_required"),
                "auth_action": manifest.get("auth_action"),
                "mini_league_status": manifest.get("mini_league_status"),
                "live_status": manifest.get("live_status"),
                "fresh_for_target_report": manifest.get("fresh_for_target_report"),
                "telemetry": manifest.get("telemetry"),
                "reuse_telemetry": manifest.get("reuse_telemetry"),
            },
            indent=2,
        )
    )
    return 0 if public_complete else 3


if __name__ == "__main__":
    raise SystemExit(main())
