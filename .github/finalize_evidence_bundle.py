from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import statistics

ROOT = Path("audit/evidence-2026-09-23")
FOLLOW = ROOT / "F_perf" / "followup_ec0960"
PRIMARY_MAIN = "918da08b892320592b9d51684e0130933a6fbb7a"
PRIMARY_FROZEN = "03abbdd9e4a1f662d4bb92f588808247d8790892"
FOLLOW_SHA = "ec0960bec30573e2585cf7076bc7bcc2611a5df6"
PROD_SHA = "967f74b82d0da2027515af40dbeb7d6a57ec9586"
CACHE_SOURCE_SHA = "bc136ac00f2aa7d8483794820932d1e275863c75"

old_manifest = {
    row["path"]: row
    for row in json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
}

def sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def summary(values):
    vals = sorted(float(x) for x in values)
    return {
        "count": len(vals),
        "min": min(vals),
        "median": statistics.median(vals),
        "max": max(vals),
        "mean": statistics.mean(vals),
        "range": max(vals) - min(vals),
    }

new_meta = {}

# Follow-up benchmark artifact.
if FOLLOW.exists():
    shutil.rmtree(FOLLOW)
(FOLLOW / "batch").mkdir(parents=True)
(FOLLOW / "scalar").mkdir(parents=True)

batch_root = Path("/tmp/batch")
if not batch_root.exists():
    raise SystemExit("missing /tmp/batch")
batch_time = (batch_root / "timestamp_utc.txt").read_text().strip()
batch_target = (batch_root / "target_sha.txt").read_text().strip()
if batch_target != FOLLOW_SHA:
    raise SystemExit(f"batch target drift: {batch_target}")

for src in sorted((batch_root / "p17-benchmark").iterdir()):
    if src.is_file():
        dst = FOLLOW / "batch" / src.name
        shutil.copy2(src, dst)
        rel = str(dst.relative_to(ROOT))
        new_meta[rel] = {
            "source": f"run_id=35879088324 job_id=107242566314 artifact_id=10760225808 path=p17-benchmark/{src.name}",
            "commit_sha": FOLLOW_SHA,
            "timestamp_utc": batch_time,
            "status": "AVAILABLE",
        }
for name in ("capture_metadata.json", "target_sha.txt", "timestamp_utc.txt"):
    src = batch_root / name
    dst = FOLLOW / "batch" / name
    shutil.copy2(src, dst)
    new_meta[str(dst.relative_to(ROOT))] = {
        "source": f"run_id=35879088324 job_id=107242566314 artifact_id=10760225808 path={name}",
        "commit_sha": FOLLOW_SHA,
        "timestamp_utc": batch_time,
        "status": "AVAILABLE",
    }

scalar_jobs_payload = json.loads(Path("/tmp/scalar_jobs.json").read_text())
jobs = scalar_jobs_payload.get("jobs", scalar_jobs_payload)
job_by_rep = {}
for job in jobs:
    m = re.search(r"\((\d+)\)", str(job.get("name") or ""))
    if m:
        job_by_rep[int(m.group(1))] = int(job["id"])

scalar_files = sorted(Path("/tmp/scalars").rglob("scalar_2043_run_*.json"))
if len(scalar_files) != 5:
    raise SystemExit(f"expected 5 scalar result files, found {len(scalar_files)}")
scalar_values = []
scalar_rows = []
for src in scalar_files:
    m = re.search(r"run_(\d+)\.json$", src.name)
    if not m:
        raise SystemExit(f"bad scalar filename: {src}")
    rep = int(m.group(1))
    row = json.loads(src.read_text())
    if int(row.get("route_count") or 0) != 2043 or int(row.get("gw_count") or 0) != 5:
        raise SystemExit(f"scalar shape drift repetition {rep}: {row}")
    scalar_values.append(float(row["elapsed_seconds"]))
    dst = FOLLOW / "scalar" / src.name
    shutil.copy2(src, dst)
    meta_src = next(iter(src.parent.glob("capture_metadata.json")), None)
    time_src = next(iter(src.parent.glob("timestamp_utc.txt")), None)
    capture_time = time_src.read_text().strip() if time_src else batch_time
    if meta_src:
        mdst = FOLLOW / "scalar" / f"capture_metadata_run_{rep}.json"
        shutil.copy2(meta_src, mdst)
        new_meta[str(mdst.relative_to(ROOT))] = {
            "source": f"run_id=35879596116 job_id={job_by_rep.get(rep)} artifact=scalar-repetition-{rep} path=capture_metadata.json",
            "commit_sha": FOLLOW_SHA,
            "timestamp_utc": capture_time,
            "status": "AVAILABLE",
        }
    new_meta[str(dst.relative_to(ROOT))] = {
        "source": f"run_id=35879596116 job_id={job_by_rep.get(rep)} artifact=scalar-repetition-{rep} path={src.name}",
        "commit_sha": FOLLOW_SHA,
        "timestamp_utc": capture_time,
        "status": "AVAILABLE",
    }
    scalar_rows.append({
        "repetition": rep,
        "job_id": job_by_rep.get(rep),
        "elapsed_seconds": float(row["elapsed_seconds"]),
        "source_path": str(dst.relative_to(ROOT)),
    })

bench = json.loads((FOLLOW / "batch" / "benchmark_diagnostics.json").read_text())
batch_values = [float(x) for x in bench["batch_2043_repeated"]["samples_seconds"]]
full_summary = {
    "_evidence_metadata": {
        "source": "workflow_dispatch run_id=35879088324 batch + workflow_dispatch run_id=35879596116 five full scalar matrix jobs",
        "commit_sha": FOLLOW_SHA,
        "timestamp_utc": batch_time,
        "status": "AVAILABLE",
    },
    "target_snapshot_sha": FOLLOW_SHA,
    "runner_label": "ubuntu-latest",
    "route_count": 2043,
    "gw_count": 5,
    "batch_5_repetitions_seconds": batch_values,
    "batch_summary": summary(batch_values),
    "scalar_5_full_repetitions": sorted(scalar_rows, key=lambda x: x["repetition"]),
    "scalar_summary": summary(scalar_values),
    "batch_profile_pstats": "F_perf/followup_ec0960/batch/batch_2043.pstats",
    "no_scalar_subset_substitution": True,
}
summary_path = FOLLOW / "benchmark_full_summary.json"
summary_path.write_text(json.dumps(full_summary, indent=2) + "\n")
new_meta[str(summary_path.relative_to(ROOT))] = {
    "source": full_summary["_evidence_metadata"]["source"],
    "commit_sha": FOLLOW_SHA,
    "timestamp_utc": batch_time,
    "status": "AVAILABLE",
}

# Follow-up snapshot. Preserve original snapshot untouched.
pr = json.loads(Path("/tmp/pr668.json").read_text())
follow_snap = {
    "_evidence_metadata": {
        "source": "GitHub pull request #668 metadata observed during final assembly + exact target SHAs from audit workflow artifacts",
        "commit_sha": PRIMARY_MAIN,
        "timestamp_utc": os.environ["FINAL_TIMESTAMP_UTC"],
        "status": "AVAILABLE",
    },
    "primary_frozen_snapshot": {
        "main_sha": PRIMARY_MAIN,
        "pr_668_head_sha": PRIMARY_FROZEN,
        "note": "A_snapshot/snapshot.json remains unchanged.",
    },
    "followup_performance_snapshot": {
        "target_sha": FOLLOW_SHA,
        "batch_run_id": 35879088324,
        "batch_job_id": 107242566314,
        "scalar_run_id": 35879596116,
        "runner_label": "ubuntu-latest",
    },
    "pr_668_observed_at_final_assembly": {
        "head_sha": ((pr.get("head") or {}).get("sha") if isinstance(pr.get("head"), dict) else pr.get("head_sha")),
        "base_sha": ((pr.get("base") or {}).get("sha") if isinstance(pr.get("base"), dict) else pr.get("base_sha")),
        "updated_at": pr.get("updated_at"),
        "state": pr.get("state"),
    },
}
fsp = ROOT / "A_snapshot" / "followup_snapshot.json"
fsp.write_text(json.dumps(follow_snap, indent=2) + "\n")
new_meta[str(fsp.relative_to(ROOT))] = {
    "source": follow_snap["_evidence_metadata"]["source"],
    "commit_sha": PRIMARY_MAIN,
    "timestamp_utc": os.environ["FINAL_TIMESTAMP_UTC"],
    "status": "AVAILABLE",
}

# Production route universe from raw S02/S14.
prod_bundle = json.loads(Path("/tmp/prod/report_bundle.json").read_text())
s14 = prod_bundle["report"]["sections"][13]["content"]
routes = s14["decision"]["routes"]
s02_rows = prod_bundle["report"]["sections"][1]["content"]["rows"]
positions = {}
names = {}
for row in s02_rows:
    element = int(row["element_id"])
    names[element] = row["player"]
    position = None
    for matchup in row.get("matchup") or []:
        position = (((matchup.get("feature_evidence") or {}).get("attacking_involvement_score") or {}).get("position"))
        if position:
            break
    positions[element] = position

from collections import Counter
route_types = Counter()
by_position = Counter()
families = Counter()
route_ids = []
for row in routes:
    route_id = str(row["route_id"])
    route_ids.append(route_id)
    route_types[str(row.get("classification"))] += 1
    m = re.fullmatch(r"1:(\d+)->(\d+)", route_id)
    if m:
        outgoing = int(m.group(1))
        families[outgoing] += 1
        by_position[positions[outgoing]] += 1

route_payload = {
    "_evidence_metadata": {
        "source": "run_id=35748919665 artifact_id=10707090457 artifact=v12-report-DEEP-35748919665/report_bundle.json paths=S02.rows+S14.decision.routes+package_search_proof+package_search_scope",
        "commit_sha": PROD_SHA,
        "timestamp_utc": "2026-09-22T16:12:41Z",
        "status": "AVAILABLE",
    },
    "status": "AVAILABLE",
    "route_count": len(routes),
    "route_type_counts": dict(route_types),
    "one_transfer_route_counts_by_outgoing_position": dict(sorted(by_position.items())),
    "core14_family_count": len(families),
    "core14_families": [
        {
            "outgoing_element": element,
            "outgoing_player": names[element],
            "position": positions[element],
            "route_count": families[element],
        }
        for element in sorted(families)
    ],
    "core13_family_count": 0,
    "core13_family_reason": "max_transfers_evaluated=1 in serialized production package_search_scope; no 2-transfer routes are present.",
    "package_search_proof": s14["package_search_proof"],
    "package_search_scope": s14["package_search_scope"],
    "complete_route_ids": route_ids,
}
route_path = ROOT / "C_routes" / "route_universe.json"
route_path.write_text(json.dumps(route_payload, indent=2, ensure_ascii=False) + "\n")
new_meta[str(route_path.relative_to(ROOT))] = {
    "source": route_payload["_evidence_metadata"]["source"],
    "commit_sha": PROD_SHA,
    "timestamp_utc": "2026-09-22T16:12:41Z",
    "status": "AVAILABLE",
}

# Production P1.2B raw timings, retained as supplemental because the source event is issue_comment.
prod_run = json.loads(Path("/tmp/prod_run.json").read_text())
log_lines = [
    line.strip()
    for line in Path("/tmp/prod_job.log").read_text(errors="replace").splitlines()
    if "[P1_2B_PERF]" in line and ("route materialization" in line)
]
timing_payload = {
    "_evidence_metadata": {
        "source": "run_id=35748919665 job_id=106817645856 GitHub Actions job log + src/engines/v12_package_utility.py at production commit",
        "commit_sha": PROD_SHA,
        "timestamp_utc": "2026-09-22T16:11:33.3923242Z",
        "status": "AVAILABLE",
    },
    "run_metadata": {
        "run_id": 35748919665,
        "job_id": 106817645856,
        "event": prod_run.get("event"),
        "head_branch": prod_run.get("head_branch"),
        "head_sha": prod_run.get("head_sha"),
        "conclusion": prod_run.get("conclusion"),
    },
    "raw_log_lines": log_lines,
    "serialized_metrics": {
        "mode": "process_pool",
        "routes": 2043,
        "unique_squads": 2043,
        "workers": 4,
        "chunksize": 63,
        "elapsed_seconds": 1805.812,
        "squad_p50_seconds": 3.462,
        "squad_p95_seconds": 3.523,
        "worker_utilization": 0.978,
        "coordination_upper_bound_seconds": 39.910,
    },
    "metric_definition_source": {
        "path": "src/engines/v12_package_utility.py",
        "commit_sha": PROD_SHA,
        "worker_elapsed_definition_lines": "845-875",
        "distribution_definition_lines": "878-895",
        "materialization_proof_lines": "952-1059",
        "worker_elapsed_definition": "time.perf_counter() around one _cumulative_lineup_horizons route evaluation",
        "proof_key": "unique_squad_elapsed_seconds",
    },
    "controlled_cold_requirement_status": "NOT AVAILABLE",
    "controlled_cold_requirement_reason": "Source run event is issue_comment, not a controlled/workflow_dispatch run.",
}
timing_path = ROOT / "F_perf" / "production_p1_2b_raw_timing.json"
timing_path.write_text(json.dumps(timing_payload, indent=2) + "\n")
new_meta[str(timing_path.relative_to(ROOT))] = {
    "source": timing_payload["_evidence_metadata"]["source"],
    "commit_sha": PROD_SHA,
    "timestamp_utc": timing_payload["_evidence_metadata"]["timestamp_utc"],
    "status": "AVAILABLE",
}

controlled_path = ROOT / "F_perf" / "controlled_cold_deep_raw.json"
controlled_payload = {
    "_evidence_metadata": {
        "source": "inspected controlled/workflow_dispatch evidence plus production timing source run_id=35748919665",
        "commit_sha": PRIMARY_MAIN,
        "timestamp_utc": os.environ["FINAL_TIMESTAMP_UTC"],
        "status": "NOT AVAILABLE",
    },
    "status": "NOT AVAILABLE",
    "reason": "Exact p50/p95 definition and units are now available from production source code/logs, but the completed raw timing source is event=issue_comment rather than a controlled/workflow_dispatch run. No completed controlled-cold source containing the requested metrics was found.",
    "supplemental_available_path": "F_perf/production_p1_2b_raw_timing.json",
}
controlled_path.write_text(json.dumps(controlled_payload, indent=2) + "\n")
new_meta[str(controlled_path.relative_to(ROOT))] = {
    "source": controlled_payload["_evidence_metadata"]["source"],
    "commit_sha": PRIMARY_MAIN,
    "timestamp_utc": os.environ["FINAL_TIMESTAMP_UTC"],
    "status": "NOT AVAILABLE",
}

# Cache inventories.
cache_dir = ROOT / "H_cache_mc"
for src, name, source, commit, ts in [
    (
        Path("/tmp/cacheapi/cache_inventory.json"),
        "actions_cache_inventory.json",
        "run_id=35880380573 job_id=107246999850 artifact_id=10760526018 GitHub Actions cache REST inventory; cache-producing run_id=35843674793",
        CACHE_SOURCE_SHA,
        "2026-09-23T15:17:04.359004Z",
    ),
    (
        Path("/tmp/cachefiles/cache_file_inventory.json"),
        "cache_file_inventory.json",
        "run_id=35880615722 job_id=107247800281 artifact_id=10760546117 exact read-only restore and file inventory; cache-producing run_id=35843674793",
        CACHE_SOURCE_SHA,
        os.environ["FINAL_TIMESTAMP_UTC"],
    ),
]:
    dst = cache_dir / name
    shutil.copy2(src, dst)
    new_meta[str(dst.relative_to(ROOT))] = {
        "source": source,
        "commit_sha": commit,
        "timestamp_utc": ts,
        "status": "AVAILABLE",
    }

cache_files = json.loads((cache_dir / "cache_file_inventory.json").read_text())
cache_summary = {
    name: {
        k: v for k, v in row.items() if k != "files"
    }
    for name, row in cache_files["caches"].items()
}
cache_md = f"""# Evidence metadata
source: GitHub Actions cache REST inventory + exact read-only restore run_id=35880615722 job_id=107247800281
commit_sha: {CACHE_SOURCE_SHA}
timestamp_utc: {os.environ["FINAL_TIMESTAMP_UTC"]}
status: AVAILABLE

Stage2 fingerprint/storage semantics remain as previously captured: V12_STAGE2_DERIVED_CACHE_DIR with sharded <key[:2]>/<key>.pkl storage and schema/key/content validation.
P1.7 fingerprint/storage semantics remain as previously captured: V12_P17_DECISION_CACHE_DIR with sharded pkl storage and optimizer/canonical/rules/config/player fingerprint inputs.
MC fingerprint/storage semantics remain as previously captured: V12_MC_SIM_CACHE_DIR with sharded pkl storage and MC code/config/projection/route/paths/seed/horizon/numpy fingerprint inputs.

Exact persisted cache evidence:
- Stage-2 key: {cache_summary["stage2"]["key"]}
  - Actions archive size: {cache_summary["stage2"]["archive_size_in_bytes_from_actions_cache_api"]} bytes
  - Restored file count: {cache_summary["stage2"]["restored_file_count"]}
  - Restored uncompressed file bytes: {cache_summary["stage2"]["restored_uncompressed_file_bytes"]}
- P1.7 key: {cache_summary["p17"]["key"]}
  - Actions archive size: {cache_summary["p17"]["archive_size_in_bytes_from_actions_cache_api"]} bytes
  - Restored file count: {cache_summary["p17"]["restored_file_count"]}
  - Restored uncompressed file bytes: {cache_summary["p17"]["restored_uncompressed_file_bytes"]}
- MC key: {cache_summary["mc"]["key"]}
  - Actions archive size: {cache_summary["mc"]["archive_size_in_bytes_from_actions_cache_api"]} bytes
  - Restored file count: {cache_summary["mc"]["restored_file_count"]}
  - Restored uncompressed file bytes: {cache_summary["mc"]["restored_uncompressed_file_bytes"]}

Per-file path, size, and SHA-256 are in H_cache_mc/cache_file_inventory.json.
Raw Actions cache API rows are in H_cache_mc/actions_cache_inventory.json.
"""
cache_fp = cache_dir / "cache_fingerprint.md"
cache_fp.write_text(cache_md)
new_meta[str(cache_fp.relative_to(ROOT))] = {
    "source": "cache source modules + GitHub Actions cache inventory and exact restore",
    "commit_sha": CACHE_SOURCE_SHA,
    "timestamp_utc": os.environ["FINAL_TIMESTAMP_UTC"],
    "status": "AVAILABLE",
}

# README status table.
readme = f"""# Evidence metadata
source: audit assembly from GitHub source, Actions runs, production artifacts, compliant workflow_dispatch benchmarks, and exact cache restores
commit_sha: {PRIMARY_MAIN}
timestamp_utc: {os.environ["FINAL_TIMESTAMP_UTC"]}
status: AVAILABLE

# V12 DEEP evidence bundle

| Item | Status | Path |
|---:|---|---|
| 1 | AVAILABLE | `A_snapshot/snapshot.json; A_snapshot/followup_snapshot.json` |
| 2 | AVAILABLE | `B_code/entrypoint.md` |
| 3 | AVAILABLE | `B_code/code_index.md` |
| 4 | AVAILABLE | `B_code/multiprocessing.md` |
| 5 | AVAILABLE | `B_code/samples/` |
| 6 | AVAILABLE | `C_routes/route_universe.json` |
| 7 | AVAILABLE | `D_e2e/workflows_index.md` |
| 8 | AVAILABLE | `D_e2e/issue431_protocol.md` |
| 9 | AVAILABLE | `D_e2e/timeline_run_*.json` |
| 10 | NOT AVAILABLE | `D_e2e/chatgpt_consumption.md` |
| 11 | AVAILABLE | `E_env/python_env.txt; numpy_config.txt; thread_env.txt; lscpu.txt` |
| 12 | AVAILABLE | `E_env/importtime.txt` |
| 13 | AVAILABLE | `F_perf/followup_ec0960/benchmark_full_summary.json` |
| 14 | AVAILABLE | `F_perf/followup_ec0960/batch/batch_2043.pstats` |
| 15 | AVAILABLE | `F_perf/run_35858764611_failed_step.log` |
| 16 | NOT AVAILABLE | `F_perf/cold_profile_19_15/; F_perf/cold_profile_19_40/` |
| 17 | NOT AVAILABLE | `F_perf/controlled_cold_deep_raw.json` (supplemental raw timing: `F_perf/production_p1_2b_raw_timing.json`) |
| 18 | AVAILABLE | `G_tests/golden_tests.md` |
| 19 | AVAILABLE | `H_cache_mc/cache_fingerprint.md; H_cache_mc/actions_cache_inventory.json; H_cache_mc/cache_file_inventory.json` |
| 20 | AVAILABLE | `H_cache_mc/mc_rng.md` |

Audit branch base: `{PRIMARY_MAIN}`.
Primary PR #668 snapshot remains frozen at `{PRIMARY_FROZEN}`; it is not overwritten.
Follow-up performance evidence is frozen at `{FOLLOW_SHA}` and is labeled separately.
No push was made to main, runtime-data-v6, or PR #668 head branch.
Item 10 remains NOT AVAILABLE because GitHub runtime evidence does not prove what an external ChatGPT session consumed or composed.
Item 16 remains NOT AVAILABLE because neither terminal 19:40 artifact contains a top-level `profile.pstats`; available stage-local pstats remain preserved.
Item 17 remains NOT AVAILABLE as a controlled-cold item because the completed p50/p95 source run is `event=issue_comment`; the raw production timing and exact metric definition are preserved separately.
MANIFEST.json intentionally omits its own checksum to avoid self-reference.
Raw binary/original artifact files carry source/SHA/time metadata through MANIFEST.json.
"""
readme_path = ROOT / "00_README.md"
readme_path.write_text(readme)
new_meta["00_README.md"] = {
    "source": "audit assembly from GitHub source, Actions runs, production artifacts, compliant workflow_dispatch benchmarks, and exact cache restores",
    "commit_sha": PRIMARY_MAIN,
    "timestamp_utc": os.environ["FINAL_TIMESTAMP_UTC"],
    "status": "AVAILABLE",
}

# Full secret scan before manifest.
secret_path = ROOT / "Z_secret_scan" / "secret_scan.md"
manifest_path = ROOT / "MANIFEST.json"
patterns = [
    ("email", re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("authorization", re.compile(rb"(?i)authorization\s*[:=]\s*[^\s]+")),
    ("credential_assignment", re.compile(rb"(?i)\b(?:token|password|passwd|cookie|fpl_access_token|fpl_session)\b\s*[:=]\s*[\"']?[^\s,}\"']+")),
    ("github_pat", re.compile(rb"(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
]

def scan(paths):
    findings = []
    for path in paths:
        raw = path.read_bytes()
        for name, pat in patterns:
            for m in pat.finditer(raw):
                findings.append((str(path.relative_to(ROOT)), name, m.start()))
    return findings

pre_paths = [
    p for p in ROOT.rglob("*")
    if p.is_file() and p not in {secret_path, manifest_path}
]
pre_findings = scan(pre_paths)
if pre_findings:
    raise SystemExit("secret scan findings before manifest: " + json.dumps(pre_findings[:20]))

secret_text = f"""# Evidence metadata
source: final full bundle byte scan + post-generation MANIFEST delta scan
commit_sha: {PRIMARY_MAIN}
timestamp_utc: {os.environ["FINAL_TIMESTAMP_UTC"]}
status: AVAILABLE

result: PASS
files_scanned_before_manifest: {len(pre_paths)}
findings_before_manifest: 0
patterns: email; Authorization header/value; token/password/passwd/cookie/FPL credential assignments; GitHub token formats
binary_files_scanned_as_bytes: yes
MANIFEST.json is scanned after generation; finalization fails on any finding.
"""
secret_path.write_text(secret_text)
new_meta[str(secret_path.relative_to(ROOT))] = {
    "source": "final full bundle byte scan + post-generation MANIFEST delta scan",
    "commit_sha": PRIMARY_MAIN,
    "timestamp_utc": os.environ["FINAL_TIMESTAMP_UTC"],
    "status": "AVAILABLE",
}

# Regenerate manifest using prior metadata for untouched paths and explicit metadata for new/changed paths.
entries = []
for path in sorted(p for p in ROOT.rglob("*") if p.is_file() and p != manifest_path):
    rel = str(path.relative_to(ROOT))
    meta = new_meta.get(rel) or old_manifest.get(rel)
    if meta is None:
        raise SystemExit(f"missing manifest metadata for {rel}")
    entries.append({
        "path": rel,
        "sha256": sha256_path(path),
        "source": meta["source"],
        "commit_sha": meta["commit_sha"],
        "timestamp_utc": meta["timestamp_utc"],
        "status": meta["status"],
    })
manifest_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n")

post_findings = scan([secret_path, manifest_path])
if post_findings:
    raise SystemExit("secret scan findings in secret/manifest: " + json.dumps(post_findings[:20]))

print(json.dumps({
    "bundle_file_count_including_manifest": len(entries) + 1,
    "manifest_entries": len(entries),
    "pre_manifest_secret_findings": 0,
    "post_manifest_secret_findings": 0,
    "batch_summary": full_summary["batch_summary"],
    "scalar_summary": full_summary["scalar_summary"],
    "route_count": route_payload["route_count"],
    "cache_summary": cache_summary,
}, indent=2))
