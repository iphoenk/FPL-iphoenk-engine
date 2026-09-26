from __future__ import annotations

"""P1 boundary between the public V6 factual tree and private personal state.

The acquisition/normalisation producer remains unchanged. This module runs only
after collection/runtime-control and before the public candidate tree is frozen.
It moves private current-team state to the private repository checkout, removes
that payload from the public candidate tree, and strips explicit auth/session
metadata from public report-prefetch observability.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


class PrivateBoundaryError(RuntimeError):
    pass


_PRIVATE_TOP_LEVEL_KEYS = {
    "auth_state",
    "report_auth_state",
    "auth_action_required",
    "auth_action",
    "personal_status",
    "authenticated_personal_deferred",
}

_PRIVATE_SCOPE_HEALTH_KEYS = {"AUTH", "PERSONAL"}
_PRIVATE_ENDPOINT_CLASSES = {"authentication", "me", "my_team"}


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file() or path.stat().st_size <= 0:
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256_json(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sanitize_public_prefetch(value: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(value)
    for key in _PRIVATE_TOP_LEVEL_KEYS:
        out.pop(key, None)

    scope_health = dict(out.get("scope_health") or {})
    for key in _PRIVATE_SCOPE_HEALTH_KEYS:
        scope_health.pop(key, None)
    if scope_health:
        out["scope_health"] = scope_health

    failures = []
    for raw in out.get("source_failures") or []:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        if (
            str(row.get("domain") or "").lower() == "official_fpl_personal"
            and str(row.get("endpoint_class") or "").lower()
            in _PRIVATE_ENDPOINT_CLASSES
        ):
            continue
        failures.append(row)
    out["source_failures"] = failures

    artifacts = []
    for raw in out.get("artifacts") or []:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        path = str(row.get("path") or "").replace("\\", "/")
        if path.endswith("/personal/current_team.json"):
            continue
        artifacts.append(row)
    if "artifacts" in out:
        out["artifacts"] = artifacts

    governance = dict(out.get("governance") or {})
    governance["private_personal_state_split"] = True
    governance["public_tree_contains_current_private_team"] = False
    out["governance"] = governance
    return out


def _sanitize_public_health(value: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(value)
    for key in _PRIVATE_TOP_LEVEL_KEYS:
        out.pop(key, None)
    out["private_personal_state_split"] = True
    return out


def split_private_personal_state(
    *,
    public_root: Path,
    private_root: Path,
) -> dict[str, Any]:
    public_root = Path(public_root)
    private_root = Path(private_root)
    if not public_root.is_dir():
        raise PrivateBoundaryError(f"public V6 root missing: {public_root}")
    if not private_root.is_dir():
        raise PrivateBoundaryError(f"private repository checkout missing: {private_root}")

    current_team_path = public_root / "personal/current_team.json"
    current_team = _read_json(current_team_path, {}) or {}
    moved = False
    private_sha = None
    generated_at = None
    if isinstance(current_team, Mapping) and current_team:
        generated_at = current_team.get("generated_at")
        private_sha = _sha256_json(current_team)
        _write_json(private_root / "personal/current_team.json", dict(current_team))
        snapshot_name = (
            str(generated_at or "unknown")
            .replace(":", "")
            .replace("+", "_plus_")
            .replace("/", "_")
        )
        _write_json(
            private_root / f"personal/snapshots/current_team_{snapshot_name}.json",
            dict(current_team),
        )
        moved = True
    if current_team_path.exists():
        current_team_path.unlink()

    latest_path = public_root / "report_prefetch/latest.json"
    latest = _read_json(latest_path, {}) or {}
    if isinstance(latest, Mapping) and latest:
        _write_json(latest_path, _sanitize_public_prefetch(latest))

    health_path = public_root / "health/report_prefetch.json"
    health = _read_json(health_path, {}) or {}
    if isinstance(health, Mapping) and health:
        _write_json(health_path, _sanitize_public_health(health))

    receipt = {
        "schema": "FPL_V6_PRIVATE_BOUNDARY_RECEIPT_V1",
        "moved_current_team": moved,
        "current_team_sha256": private_sha,
        "current_team_generated_at": generated_at,
        "public_current_team_present_after_split": current_team_path.exists(),
        "public_report_prefetch_sanitized": bool(latest),
        "public_report_prefetch_health_sanitized": bool(health),
    }
    _write_json(private_root / "personal/private_boundary_receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-root", required=True)
    parser.add_argument("--private-root", required=True)
    args = parser.parse_args()
    receipt = split_private_personal_state(
        public_root=Path(args.public_root),
        private_root=Path(args.private_root),
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "moved_current_team": receipt["moved_current_team"],
                "public_current_team_present_after_split": receipt[
                    "public_current_team_present_after_split"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
