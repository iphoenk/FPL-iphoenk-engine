from pathlib import Path


RUNTIME_WORKFLOW = Path(".github/workflows/v3-runtime.yml")
CI_WORKFLOW = Path(".github/workflows/v3-ci.yml")

CHECKOUT_SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"  # v7.0.1
SETUP_PYTHON_SHA = "5fda3b95a4ea91299a34e894583c3862153e4b97"  # v7.0.0
UPLOAD_ARTIFACT_SHA = "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"  # v7.0.1
DOWNLOAD_ARTIFACT_SHA = "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"  # v8.0.1


def test_runtime_compute_is_read_only_and_publication_is_isolated():
    workflow = RUNTIME_WORKFLOW.read_text(encoding="utf-8")
    assert "  compute:\n    permissions:\n      contents: read\n" in workflow
    assert "  publish:\n    needs: compute\n" in workflow
    assert "    permissions:\n      contents: write\n      actions: read\n" in workflow
    assert "persist-credentials: false" in workflow
    assert "GH_TOKEN: ${{ github.token }}" in workflow
    assert f"actions/upload-artifact@{UPLOAD_ARTIFACT_SHA}" in workflow
    assert f"actions/download-artifact@{DOWNLOAD_ARTIFACT_SHA}" in workflow


def test_workflows_use_full_sha_pins_and_locked_dependencies():
    runtime = RUNTIME_WORKFLOW.read_text(encoding="utf-8")
    ci = CI_WORKFLOW.read_text(encoding="utf-8")
    for workflow in (runtime, ci):
        assert f"actions/checkout@{CHECKOUT_SHA}" in workflow
        assert f"actions/setup-python@{SETUP_PYTHON_SHA}" in workflow
        assert "actions/checkout@v7" not in workflow
        assert "actions/setup-python@v7" not in workflow
        assert "persist-credentials: false" in workflow
    assert "pip install --no-deps -r requirements.lock" in runtime
    assert "pip install --no-deps -r requirements-ci.lock" in ci


def test_dependency_locks_are_exact_and_do_not_contain_ranges():
    runtime_lines = [
        line.strip()
        for line in Path("requirements.lock").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    ci_lines = [
        line.strip()
        for line in Path("requirements-ci.lock").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#") and not line.startswith("-r ")
    ]
    assert runtime_lines
    assert ci_lines
    assert all("==" in line for line in runtime_lines)
    assert all("==" in line for line in ci_lines)
    assert all(not any(token in line for token in (">=", "<=", "~=", "!=", "<", ">")) for line in runtime_lines + ci_lines)
