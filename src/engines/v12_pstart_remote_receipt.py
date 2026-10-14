"""Independent evidence verifier for a frozen GW7 P(start) occurrence.

Runs only after a private Git push, against the actual immutable objects.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess


class ForecastReadbackError(ValueError):
    pass


def _object(repo: Path, commit: str, path: str) -> bytes:
    if not commit or len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise ForecastReadbackError("INVALID_COMMIT_SHA")
    if path.startswith("/") or ".." in Path(path).parts:
        raise ForecastReadbackError("INVALID_OBJECT_PATH")
    try:
        return subprocess.check_output(["git", "-C", str(repo), "show", f"{commit}:{path}"])
    except (subprocess.CalledProcessError, OSError) as exc:
        raise ForecastReadbackError("ORIGINAL_OBJECT_UNAVAILABLE") from exc


def verify_forecast(
    receipt: dict,
    *,
    private_repo: Path,
    private_commit: str,
    occurrence_path: str,
    runtime_repo: Path,
) -> dict:
    """Return verified fields; never mutate receipt on a failed check."""
    if not receipt.get("pstart_prospective_sha256"):
        return {"pstart_prospective_remote_readback": "NOT_APPLICABLE"}
    forecast_bytes = _object(private_repo, private_commit, f"{occurrence_path}/pstart_predeadline_forecast.json")
    if hashlib.sha256(forecast_bytes).hexdigest() != receipt["pstart_prospective_sha256"]:
        raise ForecastReadbackError("PRIVATE_FORECAST_SHA256_MISMATCH")
    candidate = json.loads(forecast_bytes)
    if candidate.get("contract") != "V12_PSTART_PROSPECTIVE_PREDEADLINE_V1":
        raise ForecastReadbackError("UNRECOGNIZED_FORECAST_CONTRACT")
    frozen = datetime.fromisoformat(candidate["captured_at"].replace("Z", "+00:00"))
    deadline = datetime.fromisoformat(candidate["official_deadline"].replace("Z", "+00:00"))
    if frozen.tzinfo is None or deadline.tzinfo is None or frozen >= deadline:
        raise ForecastReadbackError("NOT_GENUINE_PREDEADLINE")
    for a, b in (("model_sha", "model_sha"), ("report_slot", "report_slot"),
                 ("planning_gw", "planning_gw")):
        if candidate.get(a) != receipt.get(b):
            raise ForecastReadbackError("FORECAST_OCCURRENCE_MISMATCH")
    rows = candidate.get("forecast_rows") or []
    ids = [row.get("element") for row in rows]
    if (len(ids) != candidate.get("universe_expected")
            or len(ids) != candidate.get("universe_observed")
            or len(ids) != len(set(ids))):
        raise ForecastReadbackError("FORECAST_UNIVERSE_INCOMPLETE")
    raw_rows = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(raw_rows).hexdigest() != candidate.get("forecast_rows_sha256"):
        raise ForecastReadbackError("FORECAST_ROWS_SHA256_MISMATCH")
    source = candidate.get("source") or {}
    digests = source.get("source_file_sha256") or {}
    allowed = {"data/v6/current/official_fpl.json", "data/v6/normalized/sources/official_fpl.json"}
    if source.get("id") != "official_fpl" or set(digests) != allowed:
        raise ForecastReadbackError("V6_SOURCE_BINDING_INCOMPLETE")
    for filename, expected in digests.items():
        original = _object(runtime_repo, receipt["runtime_sha"], filename)
        if hashlib.sha256(original).hexdigest() != expected:
            raise ForecastReadbackError("ORIGINAL_V6_BLOB_SHA256_MISMATCH")
    return {
        "pstart_prospective_remote_readback": "PASS",
        "pstart_prospective_source_sha256_readback": "PASS",
        "pstart_prospective_private_commit": private_commit,
    }
