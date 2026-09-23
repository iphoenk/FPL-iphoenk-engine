from __future__ import annotations

import cProfile

from src.engines.v12_profile_summary import build_summary, render_markdown


def load_v6_analytics_foundation() -> int:
    return sum(range(100))


def load_or_build_stage2_projections() -> int:
    return sum(i * i for i in range(100))


def combine_package_utility_surfaces() -> int:
    return max(range(100))


def run_package_monte_carlo() -> int:
    return sum(range(200))


def _synthetic_profile() -> None:
    load_v6_analytics_foundation()
    load_or_build_stage2_projections()
    combine_package_utility_surfaces()
    run_package_monte_carlo()


def test_controlled_profile_summary_classifies_required_entrypoints(tmp_path):
    profiler = cProfile.Profile()
    profiler.runcall(_synthetic_profile)
    pstats_path = tmp_path / "profile.pstats"
    profiler.dump_stats(str(pstats_path))

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

    summary = build_summary(pstats_path, log_path)

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
    for category in (
        "FOUNDATION",
        "STAGE2",
        "PACKAGE_COMBINE",
        "MONTE_CARLO",
    ):
        assert summary["categories"][category]["entrypoints"]

    markdown = render_markdown(summary)
    assert "V12 Controlled Cold Profile" in markdown
    assert "P1_4_MONTE_CARLO" in markdown
    assert "Cumulative time is inclusive" in markdown
