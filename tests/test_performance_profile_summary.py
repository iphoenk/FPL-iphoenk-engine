from __future__ import annotations

import cProfile

from src.engines.v12_profile_summary import (
    build_stage_directory_summary,
    render_markdown,
)


def load_v6_analytics_foundation() -> int:
    return sum(range(100))


def load_or_build_stage2_projections() -> int:
    return sum(i * i for i in range(100))


def combine_package_utility_surfaces() -> int:
    return max(range(100))


def run_package_monte_carlo() -> int:
    return sum(range(200))


def _dump_profile(path, fn) -> None:
    profiler = cProfile.Profile()
    profiler.runcall(fn)
    profiler.dump_stats(str(path))


def test_controlled_stage_local_profile_summary_classifies_required_entrypoints(
    tmp_path,
):
    profile_dir = tmp_path / "stage-profiles"
    profile_dir.mkdir()
    _dump_profile(
        profile_dir / "V12_ANALYTICS_FOUNDATION.pstats",
        load_v6_analytics_foundation,
    )
    _dump_profile(
        profile_dir / "P1_1_P1_3_FULL_UNIVERSE.pstats",
        load_or_build_stage2_projections,
    )
    _dump_profile(
        profile_dir / "P1_2B_PACKAGE_COMBINE.pstats",
        combine_package_utility_surfaces,
    )
    _dump_profile(
        profile_dir / "P1_4_MONTE_CARLO.pstats",
        run_package_monte_carlo,
    )

    log_path = tmp_path / "profile.log"
    log_path.write_text(
        "\n".join(
            [
                "[V12_STAGE] PASS V12_ANALYTICS_FOUNDATION elapsed_seconds=9.310",
                "[V12_STAGE] PASS P1_1_P1_3_FULL_UNIVERSE elapsed_seconds=60.075",
                "[V12_STAGE] PASS P1_2B_PACKAGE_COMBINE elapsed_seconds=5.320",
                "[V12_STAGE] PASS P1_4_MONTE_CARLO elapsed_seconds=11.250",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = build_stage_directory_summary(profile_dir, log_path)

    assert summary["profile_scope"] == "STAGE_LOCAL_PARENT_PROCESS"
    assert summary["cold_cache_contract"] == {
        "stage2_restore": False,
        "p17_restore": False,
        "mc_restore": False,
        "cache_persist": False,
    }
    assert (
        summary["stage_wall_seconds"]["P1_1_P1_3_FULL_UNIVERSE"][
            "elapsed_seconds"
        ]
        == 60.075
    )
    assert summary["limitations"]["multiprocessing_child_functions_profiled"] is False
    assert summary["limitations"]["production_latency_gate_uses_stage_wall_seconds"] is True

    for stage in (
        "V12_ANALYTICS_FOUNDATION",
        "P1_1_P1_3_FULL_UNIVERSE",
        "P1_2B_PACKAGE_COMBINE",
        "P1_4_MONTE_CARLO",
    ):
        row = summary["stage_profiles"][stage]
        assert row["status"] == "AVAILABLE"
        assert row["entrypoints"]

    markdown = render_markdown(summary)
    assert "V12 Controlled Cold Profile" in markdown
    assert "P1_4_MONTE_CARLO / MONTE_CARLO" in markdown
    assert "Child-process internals are not captured" in markdown
