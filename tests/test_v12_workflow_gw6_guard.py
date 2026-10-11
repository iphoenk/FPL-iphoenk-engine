"""Regression for the GW6-only optional MC workflow guard."""
from pathlib import Path


WORKFLOW = Path(".github/workflows/v12-integrated-report-runner.yml")


def test_gw6_forward_mc_skips_cleanly_without_non_gw6_warm_state():
    text = WORKFLOW.read_text(encoding="utf-8")
    marker = 'warm="artifacts/v12-report/gw6-warm-state.json"'
    guard = 'if [ ! -s "$warm" ]; then'
    skip = "GW6 forward MC not applicable: no GW6 warm state"
    assert marker in text
    assert guard in text
    assert skip in text
    assert text.index(guard) < text.index('planning_gw="$(python', text.index(marker))
