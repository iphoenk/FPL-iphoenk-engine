from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_p4_issue_comment_noise_cannot_replace_pending_command():
    source = _text("v12-p4-private-scenario-package.yml")
    assert "'v12-p4-private-scenario-package-command'" in source
    assert "v12-p4-private-scenario-package-noise-{0}" in source
    assert "github.event.comment.id" in source
    assert "startsWith(github.event.comment.body, '/v12-p4-build ')" in source
    assert "cancel-in-progress: false" in source


def test_perf_f_issue_comment_noise_cannot_replace_pending_serial_case():
    source = _text("v12-perf-f-production-acceptance.yml")
    assert "'v12-perf-f-production-acceptance-command'" in source
    assert "v12-perf-f-production-acceptance-noise-{0}" in source
    assert "github.event.comment.id" in source
    assert "startsWith(github.event.comment.body, '/v12-perf-f ')" in source
    assert "cancel-in-progress: false" in source
