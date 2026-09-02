from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class ApiResult:
    status: int
    payload: Any | None
    error: str | None = None


def _request_json(url: str, token: str | None) -> ApiResult:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "v3-platform-governance-audit",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=20) as response:
            return ApiResult(response.status, json.loads(response.read().decode("utf-8")))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return ApiResult(exc.code, None, body[:500])


def _check(name: str, state: str, detail: Any) -> dict[str, Any]:
    return {"name": name, "status": state, "detail": detail}


def _required_checks(branch: dict[str, Any]) -> tuple[str, set[str]]:
    protection = branch.get("protection") if isinstance(branch.get("protection"), dict) else {}
    required = protection.get("required_status_checks") if isinstance(protection.get("required_status_checks"), dict) else {}
    enforcement = str(required.get("enforcement_level") or "off")
    names: set[str] = set()
    for value in required.get("contexts") or []:
        if value:
            names.add(str(value))
    for row in required.get("checks") or []:
        if isinstance(row, dict) and row.get("context"):
            names.add(str(row["context"]))
    return enforcement, names


def _ruleset_targets_branch(ruleset: dict[str, Any], branch: str) -> bool:
    conditions = ruleset.get("conditions") if isinstance(ruleset.get("conditions"), dict) else {}
    ref_name = conditions.get("ref_name") if isinstance(conditions.get("ref_name"), dict) else {}
    include = [str(x) for x in ref_name.get("include") or []]
    exclude = [str(x) for x in ref_name.get("exclude") or []]
    canonical = f"refs/heads/{branch}"
    if canonical in exclude or branch in exclude:
        return False
    if not include:
        return True
    accepted = {canonical, branch, "~ALL", "~DEFAULT_BRANCH"}
    return bool(accepted.intersection(include))


def _ruleset_rule_types(ruleset: dict[str, Any]) -> set[str]:
    return {
        str(row.get("type"))
        for row in ruleset.get("rules") or []
        if isinstance(row, dict) and row.get("type")
    }


def _ruleset_required_checks(ruleset: dict[str, Any]) -> tuple[bool, set[str]]:
    strict = False
    names: set[str] = set()
    for row in ruleset.get("rules") or []:
        if not isinstance(row, dict) or row.get("type") != "required_status_checks":
            continue
        parameters = row.get("parameters") if isinstance(row.get("parameters"), dict) else {}
        strict = strict or bool(parameters.get("strict_required_status_checks_policy"))
        for check in parameters.get("required_status_checks") or []:
            if isinstance(check, dict) and check.get("context"):
                names.add(str(check["context"]))
            elif isinstance(check, str) and check:
                names.add(check)
    return strict, names


def _normalized_bypass_actors(rulesets: list[dict[str, Any]], branch: str) -> set[tuple[str, int, str]]:
    actors: set[tuple[str, int, str]] = set()
    for ruleset in rulesets:
        if ruleset.get("enforcement") != "active" or not _ruleset_targets_branch(ruleset, branch):
            continue
        for actor in ruleset.get("bypass_actors") or []:
            if not isinstance(actor, dict):
                continue
            try:
                actor_id = int(actor.get("actor_id"))
            except (TypeError, ValueError):
                continue
            actors.add((str(actor.get("actor_type") or ""), actor_id, str(actor.get("bypass_mode") or "")))
    return actors


def audit(
    *,
    api_url: str,
    repo: str,
    default_branch: str,
    runtime_branch: str,
    required_check: str,
    token: str | None,
    runtime_publisher_app_id: int | None = None,
) -> dict[str, Any]:
    base = api_url.rstrip("/") + f"/repos/{repo}"
    main = _request_json(f"{base}/branches/{default_branch}", token)
    runtime = _request_json(f"{base}/branches/{runtime_branch}", token)
    rulesets_summary = _request_json(f"{base}/rulesets", token)

    rulesets: list[dict[str, Any]] = []
    if rulesets_summary.status == 200 and isinstance(rulesets_summary.payload, list):
        for summary in rulesets_summary.payload:
            if not isinstance(summary, dict) or not summary.get("id"):
                continue
            detail = _request_json(f"{base}/rulesets/{summary['id']}", token)
            if detail.status == 200 and isinstance(detail.payload, dict):
                rulesets.append(detail.payload)

    main_rules = set()
    runtime_rules = set()
    main_ruleset_checks: set[str] = set()
    main_ruleset_strict = False
    for ruleset in rulesets:
        if ruleset.get("enforcement") != "active":
            continue
        if _ruleset_targets_branch(ruleset, default_branch):
            main_rules |= _ruleset_rule_types(ruleset)
            strict, names = _ruleset_required_checks(ruleset)
            main_ruleset_strict = main_ruleset_strict or strict
            main_ruleset_checks |= names
        if _ruleset_targets_branch(ruleset, runtime_branch):
            runtime_rules |= _ruleset_rule_types(ruleset)

    checks: list[dict[str, Any]] = []

    if main.status == 200 and isinstance(main.payload, dict):
        protected = bool(main.payload.get("protected"))
        checks.append(_check("MAIN_PROTECTED", "PASS" if protected else "FAIL", protected))
        enforcement, classic_names = _required_checks(main.payload)
        classic_required = enforcement != "off" and required_check in classic_names
        ruleset_required = required_check in main_ruleset_checks
        checks.append(
            _check(
                "MAIN_REQUIRED_V3_CI",
                "PASS" if classic_required or ruleset_required else "FAIL",
                {
                    "classic": {"enforcement": enforcement, "required_checks": sorted(classic_names)},
                    "ruleset": {"required_checks": sorted(main_ruleset_checks), "strict": main_ruleset_strict},
                    "expected": required_check,
                },
            )
        )
    else:
        checks.append(_check("MAIN_PROTECTED", "UNKNOWN", {"http_status": main.status, "error": main.error}))
        checks.append(_check("MAIN_REQUIRED_V3_CI", "UNKNOWN", {"http_status": main.status, "error": main.error}))

    if runtime.status == 200 and isinstance(runtime.payload, dict):
        checks.append(
            _check(
                "RUNTIME_BRANCH_NATIVE_PROTECTION",
                "PASS" if bool(runtime.payload.get("protected")) else "FAIL",
                bool(runtime.payload.get("protected")),
            )
        )
    else:
        checks.append(_check("RUNTIME_BRANCH_NATIVE_PROTECTION", "UNKNOWN", {"http_status": runtime.status, "error": runtime.error}))

    if rulesets_summary.status == 200:
        checks.append(
            _check(
                "MAIN_RULESET_PR_FORCE_DELETE_GUARDS",
                "PASS" if {"pull_request", "non_fast_forward", "deletion"}.issubset(main_rules) else "FAIL",
                {"active_rule_types": sorted(main_rules)},
            )
        )
        checks.append(
            _check(
                "RUNTIME_RULESET_UPDATE_DELETE_GUARDS",
                "PASS" if {"update", "deletion"}.issubset(runtime_rules) else "FAIL",
                {"active_rule_types": sorted(runtime_rules)},
            )
        )
        bypass_actors = _normalized_bypass_actors(rulesets, runtime_branch)
        if runtime_publisher_app_id is None:
            checks.append(
                _check(
                    "RUNTIME_PUBLISHER_BYPASS_EXACT",
                    "UNKNOWN",
                    {"reason": "V3_RUNTIME_PUBLISHER_APP_ID_NOT_DECLARED", "actors": sorted(bypass_actors)},
                )
            )
        else:
            expected = {("Integration", int(runtime_publisher_app_id), "always")}
            checks.append(
                _check(
                    "RUNTIME_PUBLISHER_BYPASS_EXACT",
                    "PASS" if bypass_actors == expected else "FAIL",
                    {"actors": sorted(bypass_actors), "expected": sorted(expected)},
                )
            )
    else:
        unknown = {"http_status": rulesets_summary.status, "error": rulesets_summary.error}
        checks.append(_check("MAIN_RULESET_PR_FORCE_DELETE_GUARDS", "UNKNOWN", unknown))
        checks.append(_check("RUNTIME_RULESET_UPDATE_DELETE_GUARDS", "UNKNOWN", unknown))
        checks.append(_check("RUNTIME_PUBLISHER_BYPASS_EXACT", "UNKNOWN", unknown))

    statuses = [row["status"] for row in checks]
    overall = "GREEN" if statuses and all(x == "PASS" for x in statuses) else ("RED" if "FAIL" in statuses else "AMBER")
    return {
        "contract": "V3_GITHUB_PLATFORM_GOVERNANCE_AUDIT_V1",
        "repository": repo,
        "default_branch": default_branch,
        "runtime_branch": runtime_branch,
        "required_v3_ci_check": required_check,
        "runtime_publisher_app_id": runtime_publisher_app_id,
        "overall": overall,
        "checks": checks,
        "policy": {
            "green_requires_explicit_platform_evidence": True,
            "unknown_never_counts_as_green": True,
            "runtime_attestation_is_defense_in_depth_not_native_branch_protection": True,
            "runtime_publisher_bypass_must_be_exact_dedicated_integration": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY", ""))
    parser.add_argument("--api-url", default=os.getenv("GITHUB_API_URL", "https://api.github.com"))
    parser.add_argument("--default-branch", default=os.getenv("V3_DEFAULT_BRANCH", "main"))
    parser.add_argument("--runtime-branch", default=os.getenv("RUNTIME_BRANCH", "runtime-data"))
    parser.add_argument("--required-check", default=os.getenv("V3_REQUIRED_CHECK", "verify"))
    parser.add_argument("--runtime-publisher-app-id", default=os.getenv("V3_RUNTIME_PUBLISHER_APP_ID", ""))
    parser.add_argument("--allow-non-green", action="store_true")
    args = parser.parse_args()
    if not args.repo:
        raise SystemExit("repository is required via --repo or GITHUB_REPOSITORY")
    publisher_app_id = int(args.runtime_publisher_app_id) if str(args.runtime_publisher_app_id).strip() else None
    result = audit(
        api_url=args.api_url,
        repo=args.repo,
        default_branch=args.default_branch,
        runtime_branch=args.runtime_branch,
        required_check=args.required_check,
        token=os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN"),
        runtime_publisher_app_id=publisher_app_id,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result["overall"] != "GREEN" and not args.allow_non_green:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
