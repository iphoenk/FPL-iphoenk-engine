from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.engines import v12_integrated_report_runner as runner


class ProbeComplete(BaseException):
    pass


def main() -> int:
    latest_path = ROOT / "data/v6/report_prefetch/latest.json"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    report_slot = (
        latest.get("target_logical_report_slot")
        or latest.get("logical_slot")
    )
    if not report_slot:
        raise RuntimeError("production report-prefetch slot unavailable")

    output_path = ROOT / "artifacts/p17-production-tie-probe.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    captured = {}
    original = runner.evaluate_packages

    def capture_direct_package(*args, **kwargs):
        result = original(*args, **kwargs)
        execution = (
            (result.get("governance") or {}).get(
                "p1_7_execution_proof"
            )
            or {}
        )
        kernel = execution.get("kernel_proof") or {}
        captured.update(
            {
                "report_slot": report_slot,
                "runtime_data_source": "runtime-data-v6",
                "execution_mode": execution.get(
                    "execution_mode"
                ),
                "route_count": execution.get("route_count"),
                "unique_squad_count": execution.get(
                    "unique_squad_count"
                ),
                "p1_7_elapsed_seconds": execution.get(
                    "elapsed_seconds"
                ),
                "kernel_proof": kernel,
                "bench_rows_evaluated": kernel.get(
                    "bench_rows_evaluated"
                ),
                "bench_primary_tie_count": kernel.get(
                    "bench_primary_tie_count"
                ),
                "bench_primary_tie_rate": kernel.get(
                    "bench_primary_tie_rate"
                ),
                "bench_scalar_fallback_count": kernel.get(
                    "bench_scalar_fallback_count"
                ),
                "bench_scalar_fallback_rate": kernel.get(
                    "bench_scalar_fallback_rate"
                ),
                "bench_zero_dnp_fast_path_family_gw_count": (
                    kernel.get(
                        "bench_zero_dnp_fast_path_family_gw_count"
                    )
                ),
                "bench_primary_boundary_count": kernel.get(
                    "bench_primary_boundary_count"
                ),
                "bench_secondary_boundary_count": kernel.get(
                    "bench_secondary_boundary_count"
                ),
                "bench_published_boundary_count": kernel.get(
                    "bench_published_boundary_count"
                ),
                "captain_scalar_boundary_fallback_count": (
                    kernel.get(
                        "captain_scalar_boundary_fallback_count"
                    )
                ),
                "captain_scalar_pair_fallback_count": (
                    kernel.get(
                        "captain_scalar_pair_fallback_count"
                    )
                ),
                "captain_max_scalar_pair_fallbacks_per_route": (
                    kernel.get(
                        "captain_max_scalar_pair_fallbacks_per_route"
                    )
                ),
                "captain_scalar_direct_cap_mean_round_count": (
                    kernel.get(
                        "captain_scalar_direct_cap_mean_round_count"
                    )
                ),
                "captain_scalar_zero_dnp_captain_count": (
                    kernel.get(
                        "captain_scalar_zero_dnp_captain_count"
                    )
                ),
                "captain_scalar_pair_round_count": (
                    kernel.get(
                        "captain_scalar_pair_round_count"
                    )
                ),
                "captain_max_scalar_pair_rounds_per_route": (
                    kernel.get(
                        "captain_max_scalar_pair_rounds_per_route"
                    )
                ),
            }
        )
        output_path.write_text(
            json.dumps(captured, indent=2),
            encoding="utf-8",
        )
        raise ProbeComplete()

    runner.evaluate_packages = capture_direct_package
    try:
        runner.run_deep(
            runtime_data_root=ROOT,
            report_slot=str(report_slot),
            output_dir=ROOT / "artifacts/p17-production-probe-run",
            checkpoint_time=None,
        )
    except ProbeComplete:
        pass
    finally:
        runner.evaluate_packages = original

    if not captured:
        raise RuntimeError("direct P1.2B production probe did not execute")
    print(json.dumps(captured, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
