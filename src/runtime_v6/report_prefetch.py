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
    exposure_artifact,
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
    PRICE_REPORT,
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
        health = {
            "schema_version": 1,
            "generated_at": manifest["generated_at"],
            "prefetch_status": (
                "GREEN"
                if manifest.get("complete") and manifest.get("fresh_for_target_report")
                else ("AMBER" if manifest.get("source_failures") or not manifest.get("complete") else "STALE")
            ),
            "personal_status": manifest.get("personal_status"),
            "league_status": manifest.get("mini_league_status"),
            "live_status": manifest.get("live_status"),
            "expected_managers": manifest.get("expected_manager_count"),
            "collected_managers": manifest.get("collected_manager_count"),
            "cache_hits": telemetry.get("cache_hits", 0),
            "cache_misses": telemetry.get("cache_misses", 0),
            "request_count": telemetry.get("request_count", 0),
            "failed_requests": telemetry.get("failed_requests", 0),
            "duration_ms": telemetry.get("duration_ms", 0),
            "fresh_for_target_report": manifest.get("fresh_for_target_report"),
            "idempotent_reuse": bool((manifest.get("idempotency") or {}).get("reused")),
        }
        write_json(self.output_root / "health/report_prefetch.json", health)

    def _noop_price_manifest(
        self,
        *,
        report_kind: str,
        slot: datetime,
        slot_identity: str,
        requested_by: str,
        requested_for_report: str,
        started: float,
    ) -> dict[str, Any]:
        max_age = int(self.config["prefetch_max_age_minutes"])
        age, fresh = freshness(self.now, slot, max_age)
        personal_reference = read_json(self.output_root / "personal/current_team.json")
        season = str(self.config.get("season") or "UNKNOWN")
        manifest = {
            "schema_version": 1,
            "request_id": str(uuid.uuid4()),
            "requested_at": iso(self.now),
            "requested_by": requested_by,
            "requested_for_report": requested_for_report,
            "report_kind": report_kind,
            "target_logical_report_slot": slot.isoformat(),
            "slot_identity": slot_identity,
            "slot_key": f"{season}|GW_NOT_APPLICABLE|{report_kind}|{slot.isoformat()}",
            "prefetch_lead_minutes": int(self.config["prefetch_lead_minutes"]),
            "generated_at": iso(self.now),
            "age_target_minutes": age,
            "prefetch_max_age_minutes": max_age,
            "fresh_for_target_report": fresh,
            "personal_requested": False,
            "personal_status": "NOT_REFRESHED_FOR_05_30_PRICE_CHECKPOINT",
            "personal_reference_generated_at": (personal_reference or {}).get("generated_at"),
            "mini_league_requested": False,
            "mini_league_status": "NOT_REQUESTED",
            "live_requested": False,
            "live_status": "NOT_REQUESTED",
            "gw": None,
            "entry_id": int(self.config["entry_id"]),
            "priority_league_id": None,
            "priority_league_name": None,
            "priority_leagues": [],
            "standings_checked_at": None,
            "submitted_picks_cache_gw": None,
            "submitted_picks_cache_complete": None,
            "submitted_picks_manager_count": None,
            "league_manager_count": None,
            "expected_manager_count": None,
            "collected_manager_count": None,
            "submitted_picks_available_count": None,
            "submitted_picks_missing_count": None,
            "coverage_percent": None,
            "live_checked_at": None,
            "source_failures": [],
            "control_failures": [],
            "telemetry": {
                "request_count": 0,
                "failed_requests": 0,
                "cache_hits": 0,
                "cache_misses": 0,
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "maximum_concurrency_used": 0,
            },
            "artifacts": [],
            "complete": True,
            "idempotency": {"reused": False},
            "governance": {
                "data_only": True,
                "decision_authority": "NONE",
                "prediction_authority": "NONE",
                "optimizer_authority": "NONE",
                "price_0530_personal_refresh_prohibited": True,
                "core_source_freshness_separate": True,
                "report_prefetch_freshness_separate": True,
                "independent_prefetch_cron": False,
            },
        }
        write_json(self.output_root / "report_prefetch/latest.json", manifest)
        self._publish_health(manifest)
        return manifest

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
        if report_kind == PRICE_REPORT:
            return self._noop_price_manifest(
                report_kind=report_kind,
                slot=slot,
                slot_identity=slot_identity,
                requested_by=requested_by,
                requested_for_report=requested_for_report,
                started=started,
            )

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
            write_json(
                self.output_root / "personal/current_team.json", team_artifact, secrets=secrets
            )
            artifacts.append(artifact_meta(self.output_root, "personal/current_team.json"))
            personal_status = (
                "AVAILABLE"
                if submitted["status"] == "AVAILABLE" and auth_state == "AVAILABLE"
                else ("DEGRADED" if submitted["status"] == "AVAILABLE" else "UNAVAILABLE")
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
                    manager_picks = exposure = None
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
                        exposure = exposure_artifact(
                            manager_picks,
                            elements,
                            bootstrap_lineage=lineage(bootstrap_result, gw=gw),
                            live_points=live_points,
                            live_lineage=(live_artifact or {}).get("lineage"),
                        )
                        exposure_relative = f"mini_leagues/{league_id}/gw_{gw}_exposure.json"
                        write_json(self.output_root / exposure_relative, exposure, secrets=secrets)
                        artifacts.append(artifact_meta(self.output_root, exposure_relative))
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
                            "coverage_percent": exposure.get("coverage_percent") if exposure else None,
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
        manifest = {
            "schema_version": 1,
            "request_id": str(uuid.uuid4()),
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
            "idempotency": {"reused": False},
            "governance": {
                "data_only": True,
                "decision_authority": "NONE",
                "prediction_authority": "NONE",
                "optimizer_authority": "NONE",
                "independence_group": "official_fpl",
                "core_source_freshness_separate": True,
                "report_prefetch_freshness_separate": True,
                "normal_hourly_personal_refresh": False,
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
    print(
        json.dumps(
            {
                "status": "COMPLETE" if manifest.get("complete") else "PARTIAL",
                "request_id": manifest.get("request_id"),
                "report_kind": manifest.get("report_kind"),
                "gw": manifest.get("gw"),
                "personal_status": manifest.get("personal_status"),
                "mini_league_status": manifest.get("mini_league_status"),
                "live_status": manifest.get("live_status"),
                "fresh_for_target_report": manifest.get("fresh_for_target_report"),
                "telemetry": manifest.get("telemetry"),
                "reuse_telemetry": manifest.get("reuse_telemetry"),
            },
            indent=2,
        )
    )
    return 0 if manifest.get("complete") else 3


if __name__ == "__main__":
    raise SystemExit(main())
