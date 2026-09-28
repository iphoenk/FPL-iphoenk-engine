from __future__ import annotations

"""Operational bounded P6 warm-window coordinator.

P6 is downstream-only. It reuses the canonical integrated V12 runner, existing
Stage3 acceptance, existing QA output and the thin private publisher. When a
safe partial executor is not yet proven, P6 deliberately performs a full
canonical recompute and records over-invalidation rather than pretending a HIT.
"""

import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Mapping

from .v12_cache_operational import LAYERS, plan_cache_behavior
from .v12_dp2_p6_handoff import occurrence_id, validate_t15_t10_window
from .v12_p6_warm_worker import CanonicalCallbacks, WarmIdentity, WarmWorker
from .v12_private_publisher import publish_private_output
from .v12_semantic_oracle import semantic_surface

POLL_SECONDS = 10

RUNTIME_FIXTURE_IDENTITY_PATHS = (
    "data/v6/current/official_fpl.json",
    "data/v6/health/publish_integrity.json",
    "data/v6/report_prefetch/latest.json",
)


class P6RuntimeError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise P6RuntimeError(f"expected JSON object: {path}")
    return value


def _git(repo: Path, *args: str, capture: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise P6RuntimeError(f"git operation failed: {' '.join(args)}")
    return (proc.stdout or "").strip()


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD")


def _remote_ref(repo: Path, ref: str) -> str:
    raw = _git(repo, "ls-remote", "origin", ref)
    if not raw:
        raise P6RuntimeError(f"remote ref unavailable: {ref}")
    return raw.split()[0]


def _changed_paths(repo: Path, old: str, new: str) -> list[str]:
    if old == new:
        return []
    return [
        row
        for row in _git(repo, "diff", "--name-only", old, new).splitlines()
        if row
    ]


def _ff_refresh(repo: Path, remote_ref: str) -> tuple[str, str, list[str]]:
    old = _head(repo)
    _git(repo, "fetch", "--quiet", "origin", remote_ref, capture=False)
    fetched = _git(repo, "rev-parse", "FETCH_HEAD")
    if fetched != old:
        _git(repo, "merge", "--ff-only", fetched, capture=False)
    new = _head(repo)
    return old, new, _changed_paths(repo, old, new)


def _hash_paths(root: Path, relative_paths: list[str]) -> str:
    digest = hashlib.sha256()
    found = False
    for relative in sorted(relative_paths):
        path = root / relative
        if not path.exists():
            continue
        found = True
        if path.is_file():
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            continue
        for child in sorted(p for p in path.rglob("*") if p.is_file()):
            digest.update(str(child.relative_to(root)).encode("utf-8"))
            digest.update(b"\0")
            digest.update(child.read_bytes())
    if not found:
        digest.update(b"UNAVAILABLE")
    return digest.hexdigest()


def classify_change(
    runtime_paths: list[str],
    private_paths: list[str],
) -> tuple[str, list[str], bool]:
    keys = [str(path) for path in runtime_paths + private_paths]
    if not keys:
        return "UNCHANGED", [], True

    runtime_lower = [path.lower() for path in runtime_paths]
    private_lower = [path.lower() for path in private_paths]

    if private_lower and not runtime_lower:
        if all("memberships" in path or "mini_league" in path for path in private_lower):
            return "MINI_LEAGUE_ONLY", keys, True
        if any(
            token in path
            for path in private_lower
            for token in ("current_team", "owner_state", "manual/")
        ):
            return "CURRENT15_CHANGE", keys, True

    if runtime_lower and not private_lower:
        if all("mini_league" in path or "mini_leagues" in path for path in runtime_lower):
            return "MINI_LEAGUE_ONLY", keys, True
        if all("price" in path for path in runtime_lower):
            return "PRICE_ONLY", keys, True

    # Never guess a selective dependency scope from broad or mixed drift.
    return "UNCERTAIN_SCOPE", keys, False


def _identity(app: Path, runtime: Path, private: Path) -> WarmIdentity:
    mc_path = app / "config/intelligence/v12_monte_carlo.json"
    mc = _read_json(mc_path)
    canonical = dict(mc.get("canonical") or {})
    rng = dict(mc.get("rng") or {})
    if int(canonical.get("minimum_actual_paths") or 0) != 500000:
        raise P6RuntimeError("canonical Monte Carlo is no longer 500k")
    if rng.get("common_random_numbers") is not True:
        raise P6RuntimeError("canonical CRN authority changed")

    mc_fingerprint = hashlib.sha256(mc_path.read_bytes()).hexdigest()
    return WarmIdentity(
        production_sha=_head(app),
        runtime_data_sha=_head(runtime),
        model_version="FPL_MASTER_V12:" + _head(app),
        schema_version="V12_CACHE_OPERATIONAL_V1",
        gw_fixture_fingerprint=_hash_paths(
            runtime,
            list(RUNTIME_FIXTURE_IDENTITY_PATHS),
        ),
        projection_lineage_fingerprint=_hash_paths(
            app,
            [
                "src/models/historical_projection.py",
                "src/engines/v12_player_minutes.py",
                "src/engines/v12_player_events.py",
                "src/engines/v12_contextual_dynamics.py",
                "config/intelligence/v12_lineup_optimizer.json",
                "config/intelligence/v12_monte_carlo.json",
            ],
        ),
        current15_fingerprint=_hash_paths(
            private,
            ["personal/current_team.json", "personal/manual"],
        ),
        owner_context_fingerprint=_hash_paths(
            private,
            [
                "personal/current_team.json",
                "personal/owner_state.json",
                "personal/memberships.json",
                "personal/manual",
            ],
        ),
        mc_authority=f"V12_MC_500K_CRN:{mc_fingerprint}",
        runtime_class="NORMALIZED",
    )


def _report_mode(report_kind: str) -> str:
    return "PRICE" if report_kind == "05:30_price" else "DEEP"


def _run_command(
    args: list[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    log_path: Path,
) -> None:
    merged = dict(os.environ)
    merged.update(env)
    proc = subprocess.run(
        args,
        cwd=cwd,
        env=merged,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(proc.stdout or "", encoding="utf-8")
    if proc.returncode != 0:
        raise P6RuntimeError(f"canonical command failed rc={proc.returncode}")


class CanonicalPipeline:
    def __init__(
        self,
        *,
        app: Path,
        runtime: Path,
        private: Path,
        workspace: Path,
        report_kind: str,
        logical_slot: str,
        run_id: str,
        private_destination_relpath: str | None = None,
        update_latest: bool = True,
        publisher_private: Path | None = None,
    ) -> None:
        self.app = app
        self.runtime = runtime
        self.private = private
        self.workspace = workspace
        self.report_kind = report_kind
        self.report_mode = _report_mode(report_kind)
        self.logical_slot = logical_slot
        self.run_id = run_id
        self.private_destination_relpath = private_destination_relpath
        self.update_latest = bool(update_latest)
        self.publisher_private = publisher_private or private
        self.sequence = 0

    def compute(
        self,
        identity: WarmIdentity,
        *,
        scenario_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        output = self.workspace / "canonical"
        if output.exists():
            shutil.rmtree(output)
        output.mkdir(parents=True)

        cache_root = self.workspace / "cache"
        for leaf in ("stage2", "p17", "mc"):
            (cache_root / leaf).mkdir(parents=True, exist_ok=True)
        env = {
            "V12_STAGE2_DERIVED_CACHE_DIR": str(cache_root / "stage2"),
            "V12_P17_DECISION_CACHE_DIR": str(cache_root / "p17"),
            "V12_MC_SIM_CACHE_DIR": str(cache_root / "mc"),
            "V12_PRIVATE_CACHE_PROFILE": os.environ.get(
                "V12_PRIVATE_CACHE_PROFILE",
                "SECURE_ENCRYPTED_PERSONAL_CACHE",
            ),
            "FPL_V12_PRIVATE_CACHE_KEY_B64": os.environ.get(
                "FPL_V12_PRIVATE_CACHE_KEY_B64",
                "",
            ),
        }

        runner_args = [
            sys.executable,
            "-m",
            "src.engines.v12_integrated_report_runner",
            "--runtime-data-root",
            str(self.runtime),
            "--private-data-root",
            str(self.private),
            "--disable-legacy-private-sources",
            "--require-private-personal",
            "--report-mode",
            self.report_mode,
            "--report-slot",
            self.logical_slot,
            "--output-dir",
            str(output),
        ]
        if scenario_overrides:
            if self.report_mode != "DEEP":
                raise P6RuntimeError("P4 scenario overrides require DEEP mode")
            scenario_input = (
                self.workspace
                / "private-inputs"
                / f"scenario-{self.sequence:03d}.json"
            )
            scenario_input.parent.mkdir(parents=True, exist_ok=True)
            scenario_input.write_text(
                json.dumps(
                    dict(scenario_overrides),
                    sort_keys=True,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            runner_args.extend(
                ["--scenario-overrides-file", str(scenario_input)]
            )

        _run_command(
            runner_args,
            cwd=self.app,
            env=env,
            log_path=self.workspace / "private-logs" / f"runner-{self.sequence:03d}.log",
        )
        self.sequence += 1

        stage3_path = output / "stage3_acceptance.json"
        if self.report_mode == "PRICE":
            stage3_path.write_text(
                json.dumps(
                    {
                        "status": "NOT_APPLICABLE",
                        "report_mode": "PRICE",
                        "reason": (
                            "PRICE delivery barrier does not execute or alter Stage3/MC"
                        ),
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        else:
            _run_command(
                [
                    sys.executable,
                    "-m",
                    "src.engines.v12_stage3_acceptance",
                    "--bundle",
                    str(output / "report_bundle.json"),
                    "--runtime-data-root",
                    str(self.runtime),
                    "--private-data-root",
                    str(self.private),
                    "--model-sha",
                    identity.production_sha,
                    "--runtime-sha",
                    identity.runtime_data_sha,
                    "--canonical",
                    str(
                        self.app
                        / "control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt"
                    ),
                    "--output",
                    str(stage3_path),
                ],
                cwd=self.app,
                env=env,
                log_path=self.workspace
                / "private-logs"
                / f"stage3-{self.sequence:03d}.log",
            )
            self.sequence += 1

        bundle = _read_json(output / "report_bundle.json")
        proof = _read_json(output / "execution_proof.json")
        stage3 = _read_json(stage3_path)
        if str(bundle.get("runner_status") or "").upper() != "PASS":
            raise P6RuntimeError("canonical runner_status is not PASS")
        for key in ("pre_render_qa", "post_render_qa", "human_facing_qa"):
            if str((bundle.get(key) or {}).get("status") or "").upper() != "PASS":
                raise P6RuntimeError(f"canonical QA failed: {key}")
        if str(stage3.get("status") or "").upper() not in {
            "PASS",
            "NOT_APPLICABLE",
        }:
            raise P6RuntimeError("Stage3 acceptance is not publishable")

        if self.report_mode == "DEEP":
            governed_surface = semantic_surface(bundle)
        else:
            governed_surface = {
                "report_mode": "PRICE",
                "report": bundle.get("report"),
                "runner_status": bundle.get("runner_status"),
            }
        return {
            "identity": asdict(identity),
            "output_dir": str(output),
            "bundle": bundle,
            "execution_proof": proof,
            "stage3_acceptance": stage3,
            "semantic_surface": governed_surface,
        }

    def publish(self, state: Mapping[str, Any]) -> dict[str, Any]:
        identity = WarmIdentity(**dict(state["identity"]))
        receipt = publish_private_output(
            canonical_dir=Path(str(state["output_dir"])),
            private_root=self.publisher_private,
            run_id=self.run_id,
            season=None,
            model_sha=identity.production_sha,
            runtime_sha=identity.runtime_data_sha,
            destination_relpath=self.private_destination_relpath,
            update_latest=self.update_latest,
        )
        _git(
            self.publisher_private,
            "config",
            "user.name",
            "github-actions[bot]",
            capture=False,
        )
        _git(
            self.publisher_private,
            "config",
            "user.email",
            "41898282+github-actions[bot]@users.noreply.github.com",
            capture=False,
        )
        if self.private_destination_relpath:
            _git(
                self.private,
                "add",
                "--",
                self.private_destination_relpath,
                capture=False,
            )
        else:
            _git(self.publisher_private, "add", "latest", "reports", capture=False)
        staged = _git(self.publisher_private, "diff", "--cached", "--name-only")
        if staged:
            _git(
                self.private,
                "commit",
                "-m",
                (
                    f"report(v12): P6 private {self.report_mode} "
                    f"{self.logical_slot} run {self.run_id}"
                ),
                capture=False,
            )
            _git(
                self.private,
                "pull",
                "--rebase",
                "origin",
                "main",
                capture=False,
            )
            _git(
                self.private,
                "push",
                "origin",
                "HEAD:main",
                capture=False,
            )
        local = _head(self.publisher_private)
        remote = _remote_ref(self.publisher_private, "refs/heads/main")
        if local != remote:
            raise P6RuntimeError("private publication remote verification failed")
        return {**receipt, "private_remote_sha": remote}


def _load_scenario_package(private: Path) -> dict[str, Any] | None:
    for candidate in (
        private / "scenarios/latest.json",
        private / "scenarios/current.json",
    ):
        if candidate.is_file():
            return _read_json(candidate)
    return None


def _sleep_until(target: datetime) -> None:
    while True:
        remaining = target.timestamp() - datetime.now().astimezone().timestamp()
        if remaining <= 0:
            return
        time.sleep(min(float(POLL_SECONDS), remaining))


def _assert_main_unchanged(app: Path, production_sha: str) -> None:
    observed = _remote_ref(app, "refs/heads/main")
    if observed != production_sha:
        raise P6RuntimeError(
            f"wrong base during P6 warm window: {observed} != {production_sha}"
        )


def _wait_for_same_occurrence_prefetch(
    runtime: Path,
    *,
    logical_slot: str,
    freeze_target: datetime,
) -> None:
    path = runtime / "data/v6/report_prefetch/latest.json"
    while datetime.now().astimezone().timestamp() <= freeze_target.timestamp():
        if path.is_file():
            payload = _read_json(path)
            observed = str(payload.get("target_logical_report_slot") or "")
            fresh = payload.get("fresh_for_target_report") is True
            if observed == logical_slot and fresh:
                return
        _ff_refresh(runtime, "runtime-data-v6")
        time.sleep(POLL_SECONDS)
    raise P6RuntimeError(
        "same-occurrence factual/report prefetch did not become ready before T-10"
    )


def _full_recompute_states(expected: Mapping[str, str]) -> dict[str, str]:
    return {
        layer: (
            "NOT_APPLICABLE"
            if expected[layer] == "NOT_APPLICABLE"
            else "MISS"
        )
        for layer in LAYERS
    }


def run_window(
    *,
    app: Path,
    runtime: Path,
    private: Path,
    workspace: Path,
    report_kind: str,
    logical_slot: str,
    freeze_target_at: str,
    occurrence: str,
    run_id: str,
) -> dict[str, Any]:
    logical = datetime.fromisoformat(logical_slot.replace("Z", "+00:00"))
    freeze = datetime.fromisoformat(freeze_target_at.replace("Z", "+00:00"))
    release = datetime.fromtimestamp(
        logical.timestamp() - 15 * 60,
        tz=logical.tzinfo,
    )
    validate_t15_t10_window(
        logical_slot=logical.isoformat(),
        release_at=release.isoformat(),
        freeze_target_at=freeze.isoformat(),
    )
    expected_occurrence = occurrence_id(
        report_kind=report_kind,
        logical_slot=logical.isoformat(),
    )
    if occurrence != expected_occurrence:
        raise P6RuntimeError("cross-occurrence P6 invocation rejected")
    if logical.timestamp() - datetime.now().astimezone().timestamp() > 6 * 60 * 60:
        raise P6RuntimeError("P6 window exceeds bounded lifetime")

    baseline_identity = _identity(app, runtime, private)
    _assert_main_unchanged(app, baseline_identity.production_sha)
    _wait_for_same_occurrence_prefetch(
        runtime,
        logical_slot=logical.isoformat(),
        freeze_target=freeze,
    )
    # The prefetch can advance runtime-data-v6; bind identity only after it is ready.
    baseline_identity = _identity(app, runtime, private)

    pipeline = CanonicalPipeline(
        app=app,
        runtime=runtime,
        private=private,
        workspace=workspace,
        report_kind=report_kind,
        logical_slot=logical.isoformat(),
        run_id=run_id,
    )
    prepared = pipeline.compute(baseline_identity)

    # Exact T-10 freeze. Drift between bootstrap and freeze is fail-closed recompute.
    _sleep_until(freeze)
    _assert_main_unchanged(app, baseline_identity.production_sha)
    _, _, freeze_runtime_paths = _ff_refresh(runtime, "runtime-data-v6")
    _, _, freeze_private_paths = _ff_refresh(private, "main")
    freeze_class, freeze_keys, freeze_certain = classify_change(
        freeze_runtime_paths,
        freeze_private_paths,
    )
    if freeze_class != "UNCHANGED":
        plan_cache_behavior(
            freeze_class,
            affected_dependency_keys=freeze_keys,
            scope_certain=freeze_certain,
        )
        baseline_identity = _identity(app, runtime, private)
        prepared = pipeline.compute(baseline_identity)

    frozen_identity = baseline_identity
    frozen_state = prepared

    # Visible slot is accepted by an already-running worker: this is T0.
    _sleep_until(logical)
    t0_wall = datetime.now().astimezone().isoformat()
    _assert_main_unchanged(app, frozen_identity.production_sha)
    _, _, runtime_paths = _ff_refresh(runtime, "runtime-data-v6")
    _, _, private_paths = _ff_refresh(private, "main")
    change_class, dependency_keys, scope_certain = classify_change(
        runtime_paths,
        private_paths,
    )
    final_identity = _identity(app, runtime, private)
    current_state: dict[str, Any] = dict(frozen_state)

    def load_canonical(
        identity: WarmIdentity,
        private_state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return current_state

    def recompute(
        state: Mapping[str, Any],
        change: Mapping[str, Any],
        plan: Any,
    ) -> tuple[
        Mapping[str, Any],
        Mapping[str, str],
        Mapping[str, list[str]],
    ]:
        nonlocal current_state
        if str(change.get("change_class") or "").upper() == "UNCHANGED":
            current_state = dict(state)
            return current_state, dict(plan.expected), {}
        current_state = pipeline.compute(final_identity)
        return current_state, _full_recompute_states(plan.expected), {}

    def stage3(state: Mapping[str, Any]) -> Mapping[str, Any]:
        return dict(state["stage3_acceptance"])

    def render(
        state: Mapping[str, Any],
        stage3_state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if pipeline.report_mode == "PRICE":
            return {"semantic_surface": dict(state["semantic_surface"])}
        return dict(state["bundle"])

    def qa(
        rendered: Mapping[str, Any],
        stage3_state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if pipeline.report_mode == "PRICE":
            return {"status": "PASS"}
        for key in ("pre_render_qa", "post_render_qa", "human_facing_qa"):
            if str((rendered.get(key) or {}).get("status") or "").upper() != "PASS":
                return {"status": "FAIL", "failed_key": key}
        return {"status": "PASS"}

    def private_publish(
        rendered: Mapping[str, Any],
        qa_state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return pipeline.publish(current_state)

    worker = WarmWorker(
        identity=frozen_identity,
        private_state={
            "owner_context_fingerprint": frozen_identity.owner_context_fingerprint,
            "current15_fingerprint": frozen_identity.current15_fingerprint,
        },
        scenario_package=_load_scenario_package(private),
        callbacks=CanonicalCallbacks(
            load_canonical_state=load_canonical,
            recompute=recompute,
            stage3=stage3,
            render=render,
            qa=qa,
            private_publish=private_publish,
        ),
        ttl_seconds=min(
            5 * 60 * 60 + 45 * 60,
            max(60, int(logical.timestamp() - freeze.timestamp()) + 900),
        ),
    )
    worker.start()
    result = worker.apply_change(
        {
            "change_class": change_class,
            "affected_dependency_keys": dependency_keys,
            "scope_certain": scope_certain,
        }
    )
    worker.shutdown()
    result["occurrence_id"] = occurrence
    result["t0_wall"] = t0_wall
    result["final_identity"] = asdict(final_identity)
    result["canonical_cold_oracle_required_for_perf_f"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="FPL V12 P6 warm window")
    parser.add_argument("--app-root", default=".")
    parser.add_argument("--runtime-data-root", required=True)
    parser.add_argument("--private-root", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--report-kind", required=True)
    parser.add_argument("--logical-slot", required=True)
    parser.add_argument("--freeze-target-at", required=True)
    parser.add_argument("--occurrence-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--result-out", required=True)
    args = parser.parse_args()

    result = run_window(
        app=Path(args.app_root).resolve(),
        runtime=Path(args.runtime_data_root).resolve(),
        private=Path(args.private_root).resolve(),
        workspace=Path(args.workspace).resolve(),
        report_kind=args.report_kind,
        logical_slot=args.logical_slot,
        freeze_target_at=args.freeze_target_at,
        occurrence=args.occurrence_id,
        run_id=args.run_id,
    )
    out = Path(args.result_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Fingerprints/timings only. Manager plaintext is never written here.
    out.write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "occurrence_id": result["occurrence_id"],
                "change_class": result["change_class"],
                "total_seconds": result["total_seconds"],
                "private_delivery_status": result["private_delivery_status"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
