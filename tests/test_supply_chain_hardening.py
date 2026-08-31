from pathlib import Path


RUNTIME_WORKFLOW = Path(".github/workflows/v3-runtime.yml")
CI_WORKFLOW = Path(".github/workflows/v3-ci.yml")


def test_runtime_compute_is_read_only_and_publication_is_isolated():
    workflow = RUNTIME_WORKFLOW.read_text(encoding="utf-8")
    assert "  compute:\n    permissions:\n      contents: read\n" in workflow
    assert "  publish:\n    needs: compute\n" in workflow
    assert "    permissions:\n      contents: write\n      actions: read\n" in workflow
    assert "persist-credentials: false" in workflow
    assert "GH_TOKEN: ${{ github.token }}" in workflow
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in workflow
    assert "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093" in workflow


def test_workflows_use_full_sha_pins_and_locked_dependencies():
    runtime = RUNTIME_WORKFLOW.read_text(encoding="utf-8")
    ci = CI_WORKFLOW.read_text(encoding="utf-8")
    for workflow in (runtime, ci):
        assert "actions/checkout@11d5960a326750d5838078e36cf38b85af677262" in workflow
        assert "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065" in workflow
        assert "actions/checkout@v4" not in workflow
        assert "actions/setup-python@v5" not in workflow
        assert "persist-credentials: false" in workflow
    assert "pip install --no-deps -r requirements.lock" in runtime
    assert "pip install --no-deps -r requirements-ci.lock" in ci


def _dependency_lines(path: str) -> tuple[list[str], list[str]]:
    directives: list[str] = []
    dependencies: list[str] = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "--require-hashes" or line.startswith("-r "):
            directives.append(line)
            continue
        dependencies.append(line)
    return directives, dependencies


def test_dependency_locks_are_exact_and_do_not_contain_ranges():
    runtime_directives, runtime_lines = _dependency_lines("requirements.lock")
    ci_directives, ci_lines = _dependency_lines("requirements-ci.lock")

    assert "--require-hashes" in runtime_directives
    assert "--require-hashes" in ci_directives
    assert "-r requirements.lock" in ci_directives
    assert runtime_lines
    assert ci_lines
    assert all("==" in line for line in runtime_lines)
    assert all("==" in line for line in ci_lines)
    assert all("--hash=sha256:" in line for line in runtime_lines + ci_lines)
    assert all(not any(token in line for token in (">=", "<=", "~=", "!=", "<", ">")) for line in runtime_lines + ci_lines)
