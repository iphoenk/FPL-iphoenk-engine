from __future__ import annotations

import argparse
import json
import os
import shlex
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_POLICY_PATH = Path("config/v6/schedule_policy.json")
_ALLOWED_PREFETCH_SCOPES = {"personal", "mini_league", "live"}
_SCOPE_ALIASES = {"mini": "mini_league", "league": "mini_league"}
_BOOLEAN_TRUE = {"true", "1", "yes"}
_BOOLEAN_FALSE = {"false", "0", "no"}


class WorkflowControlError(ValueError):
    pass


def scheduled_cron_kinds(policy: dict[str, Any]) -> dict[str, str]:
    configured = policy.get("scheduled_crons_utc")
    if configured is None:
        configured = [
            {"cron": policy.get("primary_cron_utc"), "kind": "primary"},
            {"cron": policy.get("recovery_cron_utc"), "kind": "recovery"},
        ]
    if not isinstance(configured, list) or not configured:
        raise WorkflowControlError("V6 schedule policy requires scheduled_crons_utc")

    scheduled: dict[str, str] = {}
    for entry in configured:
        if not isinstance(entry, dict):
            raise WorkflowControlError("V6 scheduled_crons_utc entries must be objects")
        cron = str(entry.get("cron") or "").strip()
        kind = str(entry.get("kind") or "").strip()
        if not cron or kind not in {"primary", "recovery"}:
            raise WorkflowControlError("V6 scheduled cron requires cron plus primary/recovery kind")
        if cron in scheduled:
            raise WorkflowControlError(f"duplicate V6 scheduled cron: {cron}")
        scheduled[cron] = kind

    primary = str(policy.get("primary_cron_utc") or "").strip()
    recovery = str(policy.get("recovery_cron_utc") or "").strip()
    if scheduled.get(primary) != "primary":
        raise WorkflowControlError("primary_cron_utc must identify the primary scheduled cron")
    if scheduled.get(recovery) != "recovery":
        raise WorkflowControlError("recovery_cron_utc must identify a recovery scheduled cron")
    expected_attempts = int(policy.get("natural_schedule_redundancy_attempts_per_hour") or len(scheduled))
    if expected_attempts != len(scheduled):
        raise WorkflowControlError("V6 natural scheduler redundancy attempt count mismatch")
    return scheduled


def load_policy(path: Path | str = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("engine") != "V6_FRESH_DATA_PLATFORM":
        raise WorkflowControlError("unexpected V6 schedule policy engine")
    scheduled_cron_kinds(payload)
    return payload


def authorize_dispatch(
    policy: dict[str, Any],
    *,
    actor: str,
    repository_owner: str,
    mode: str,
    reason: str,
    manual_confirm: str = "",
) -> str:
    if actor != repository_owner:
        raise WorkflowControlError("V6 governed dispatch is restricted to the repository owner")
    if not str(reason).strip():
        raise WorkflowControlError("V6 governed dispatch requires an audit reason")

    control = dict(policy.get(mode) or {})
    if mode == "master_orchestrated":
        if control.get("enabled") is not True or control.get("authoritative_runtime_snapshot") is not True:
            raise WorkflowControlError("V6 master orchestration is not authorized")
    elif mode == "manual_recovery":
        if control.get("enabled") is not True:
            raise WorkflowControlError("V6 governed manual recovery is disabled")
        if manual_confirm != str(control.get("confirmation_phrase") or ""):
            raise WorkflowControlError("V6 manual recovery confirmation phrase mismatch")
    elif mode == "report_prefetch":
        if control.get("enabled") is not True or control.get("report_driven") is not True:
            raise WorkflowControlError("V6 report prefetch is disabled")
        if control.get("independent_cron") is not False:
            raise WorkflowControlError("V6 report prefetch policy must prohibit independent cron")
        if control.get("counts_as_completed_operational_slot") is not False:
            raise WorkflowControlError("V6 report prefetch must not complete a core operational slot")
    else:
        raise WorkflowControlError(f"Unsupported V6 governed dispatch mode: {mode}")
    return mode


def _issue_command(comment_body: str) -> str:
    tokens = shlex.split(str(comment_body or "").strip())
    return tokens[0] if tokens else ""


def authorize_issue(
    policy: dict[str, Any],
    *,
    actor: str,
    repository_owner: str,
    issue_number: int,
    comment_body: str,
) -> str:
    if actor != repository_owner:
        raise WorkflowControlError("V6 governed issue command is restricted to repository owner")
    command = _issue_command(comment_body)
    controls = {
        str((policy.get("master_orchestrated") or {}).get("issue_comment_command") or ""): "master_orchestrated",
        str((policy.get("report_prefetch") or {}).get("issue_comment_command") or ""): "report_prefetch",
    }
    mode = controls.get(command)
    if not mode:
        raise WorkflowControlError("V6 governed issue command mismatch")
    control = dict(policy.get(mode) or {})
    if control.get("enabled") is not True:
        raise WorkflowControlError(f"V6 {mode} is disabled")
    if int(issue_number) != int(control.get("control_issue_number") or 0):
        raise WorkflowControlError("V6 governed control issue number mismatch")
    return mode


def classify_invocation(
    policy: dict[str, Any],
    *,
    event_name: str,
    event: dict[str, Any],
) -> str:
    if event_name == "schedule":
        return scheduled_cron_kinds(policy).get(str(event.get("schedule") or ""), "scheduled_unknown")

    if event_name == "issue_comment":
        command = _issue_command(str((event.get("comment") or {}).get("body") or ""))
        for mode in ("master_orchestrated", "report_prefetch"):
            control = dict(policy.get(mode) or {})
            if command == str(control.get("issue_comment_command") or ""):
                return str(control.get("schedule_kind") or mode)
        return "governed_issue_command_unknown"

    if event_name == "workflow_dispatch":
        mode = str((event.get("inputs") or {}).get("mode") or "")
        control = dict(policy.get(mode) or {})
        if mode in {"master_orchestrated", "manual_recovery", "report_prefetch"} and control.get("enabled") is True:
            return str(control.get("schedule_kind") or mode)
        return "governed_dispatch_unknown"

    return "non_production_local"


def _parse_issue_prefetch_values(comment_body: str) -> dict[str, str]:
    tokens = shlex.split(str(comment_body or ""))
    values: dict[str, str] = {}
    for token in tokens[1:]:
        if "=" not in token:
            raise WorkflowControlError(f"Malformed report-prefetch token: {token}")
        key, value = token.split("=", 1)
        if key in values:
            raise WorkflowControlError(f"Duplicate report-prefetch argument: {key}")
        values[key] = value
    allowed = {"report_kind", "logical_slot", "scope", "gw_from", "gw_to", "force", "reason"}
    unknown = set(values) - allowed
    if unknown:
        raise WorkflowControlError(f"Unsupported report-prefetch arguments: {sorted(unknown)}")
    if not str(values.get("reason") or "").strip():
        raise WorkflowControlError("Issue-command report prefetch requires reason=<audit reason>")
    return values


def _parse_bool(value: Any) -> bool:
    normalized = str(value or "false").strip().lower()
    if normalized in _BOOLEAN_TRUE:
        return True
    if normalized in _BOOLEAN_FALSE:
        return False
    raise WorkflowControlError("force must be boolean")


def resolve_prefetch(
    policy: dict[str, Any],
    *,
    event_name: str,
    comment_body: str = "",
    dispatch_values: dict[str, Any] | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    prefetch = dict(policy.get("report_prefetch") or {})
    if prefetch.get("enabled") is not True or prefetch.get("report_driven") is not True:
        raise WorkflowControlError("V6 report prefetch is disabled")
    if prefetch.get("counts_as_completed_operational_slot") is not False:
        raise WorkflowControlError("V6 report prefetch cannot complete the core operational slot")

    values = (
        _parse_issue_prefetch_values(comment_body)
        if event_name == "issue_comment"
        else {key: value for key, value in dict(dispatch_values or {}).items()}
    )
    report_kind = str(values.get("report_kind") or "").strip()
    if report_kind not in set(prefetch.get("supported_report_kinds") or []):
        raise WorkflowControlError(f"Unsupported report_kind={report_kind}")

    historical = report_kind == "historical_backfill"
    logical_slot = str(values.get("logical_slot") or "").strip()
    scope_raw = str(values.get("scope") or "").strip()
    scopes = [_SCOPE_ALIASES.get(part.strip(), part.strip()) for part in scope_raw.split(",") if part.strip()]
    if len(scopes) != len(set(scopes)):
        raise WorkflowControlError("report-prefetch scope contains duplicates")
    unknown_scopes = set(scopes) - _ALLOWED_PREFETCH_SCOPES
    if unknown_scopes:
        raise WorkflowControlError(f"Unsupported report-prefetch scopes: {sorted(unknown_scopes)}")

    gw_from = ""
    gw_to = ""
    if historical:
        if logical_slot:
            raise WorkflowControlError("historical_backfill does not accept logical_slot")
        if scopes != ["mini_league"]:
            raise WorkflowControlError("historical_backfill requires scope=mini_league")
        try:
            gw_from_value = int(str(values.get("gw_from") or ""))
            gw_to_value = int(str(values.get("gw_to") or ""))
        except ValueError as exc:
            raise WorkflowControlError("historical_backfill requires integer gw_from and gw_to") from exc
        if gw_from_value < 1 or gw_to_value < 1 or gw_from_value > gw_to_value:
            raise WorkflowControlError("historical_backfill GW range is invalid")
        gw_from, gw_to = str(gw_from_value), str(gw_to_value)
    else:
        if values.get("gw_from") or values.get("gw_to"):
            raise WorkflowControlError("gw_from/gw_to are valid only for historical_backfill")
        if not logical_slot:
            raise WorkflowControlError("report-prefetch logical_slot is required")
        try:
            parsed = datetime.fromisoformat(logical_slot)
        except ValueError as exc:
            raise WorkflowControlError("report-prefetch logical_slot must be ISO-8601") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise WorkflowControlError("report-prefetch logical_slot must include timezone offset")
        if report_kind != "ad_hoc" and scopes:
            raise WorkflowControlError("scope override is allowed only for ad_hoc report prefetch")
        if report_kind == "ad_hoc" and not scopes:
            raise WorkflowControlError("ad_hoc report prefetch requires a non-empty scope")

    force = _parse_bool(values.get("force"))
    env = {
        "V6_PREFETCH_REPORT_KIND": report_kind,
        "V6_PREFETCH_LOGICAL_SLOT": logical_slot,
        "V6_PREFETCH_PERSONAL": "true" if "personal" in scopes else "false",
        "V6_PREFETCH_MINI_LEAGUE": "true" if "mini_league" in scopes else "false",
        "V6_PREFETCH_LIVE": "true" if "live" in scopes else "false",
        "V6_PREFETCH_GW_FROM": gw_from,
        "V6_PREFETCH_GW_TO": gw_to,
        "V6_PREFETCH_FORCE": "true" if force else "false",
    }
    summary = {
        "report_kind": report_kind,
        "logical_slot": logical_slot,
        "scope": scopes,
        "gw_from": gw_from,
        "gw_to": gw_to,
        "force": force,
    }
    return env, summary


def _append(path_env: str, values: dict[str, str]) -> None:
    path = os.environ.get(path_env)
    if not path:
        raise WorkflowControlError(f"missing {path_env}")
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def _event() -> dict[str, Any]:
    path = os.environ.get("GITHUB_EVENT_PATH")
    return json.loads(Path(path).read_text(encoding="utf-8")) if path else {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Governed V6 GitHub workflow control plane")
    parser.add_argument("command", choices=["authorize-dispatch", "authorize-issue", "classify", "resolve-prefetch"])
    parser.add_argument("--policy", default=str(DEFAULT_POLICY_PATH))
    args = parser.parse_args()
    policy = load_policy(args.policy)

    try:
        if args.command == "authorize-dispatch":
            mode = authorize_dispatch(
                policy,
                actor=str(os.environ.get("GITHUB_ACTOR") or ""),
                repository_owner=str(os.environ.get("GITHUB_REPOSITORY_OWNER") or ""),
                mode=str(os.environ.get("V6_DISPATCH_MODE") or ""),
                reason=str(os.environ.get("V6_DISPATCH_REASON") or ""),
                manual_confirm=str(os.environ.get("V6_MANUAL_CONFIRM") or ""),
            )
            print(f"Governed V6 {mode} dispatch authorized")
        elif args.command == "authorize-issue":
            mode = authorize_issue(
                policy,
                actor=str(os.environ.get("GITHUB_ACTOR") or ""),
                repository_owner=str(os.environ.get("GITHUB_REPOSITORY_OWNER") or ""),
                issue_number=int(os.environ.get("V6_ISSUE_NUMBER") or 0),
                comment_body=str(os.environ.get("V6_COMMENT_BODY") or ""),
            )
            print(f"Governed V6 {mode} issue-command authorized")
        elif args.command == "classify":
            kind = classify_invocation(
                policy,
                event_name=str(os.environ.get("GITHUB_EVENT_NAME") or ""),
                event=_event(),
            )
            _append("GITHUB_ENV", {"V6_SCHEDULE_KIND": kind})
            _append("GITHUB_OUTPUT", {"kind": kind})
            print(f"V6 schedule kind: {kind}")
        else:
            event_name = str(os.environ.get("GITHUB_EVENT_NAME") or "")
            dispatch_values = {
                "report_kind": os.environ.get("V6_DISPATCH_REPORT_KIND") or "",
                "logical_slot": os.environ.get("V6_DISPATCH_LOGICAL_SLOT") or "",
                "scope": os.environ.get("V6_DISPATCH_SCOPE") or "",
                "gw_from": os.environ.get("V6_DISPATCH_GW_FROM") or "",
                "gw_to": os.environ.get("V6_DISPATCH_GW_TO") or "",
                "force": os.environ.get("V6_DISPATCH_FORCE") or "false",
            }
            env, summary = resolve_prefetch(
                policy,
                event_name=event_name,
                comment_body=str(os.environ.get("V6_COMMENT_BODY") or ""),
                dispatch_values=dispatch_values,
            )
            _append("GITHUB_ENV", env)
            print(json.dumps(summary, ensure_ascii=False))
    except WorkflowControlError as exc:
        raise SystemExit(str(exc)) from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
