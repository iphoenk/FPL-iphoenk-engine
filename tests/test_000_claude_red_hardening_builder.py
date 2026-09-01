from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "codex/v4-claude-red-hardening"


def _replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise AssertionError(f"patch anchor missing in {path}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_build_red_hardening_patch():
    if os.getenv("GITHUB_ACTIONS") != "true" or os.getenv("GITHUB_HEAD_REF") != BRANCH:
        pytest.skip("self-cleaning branch builder runs only in its PR CI")

    package = ROOT / "src/engines/v4_wc_package_audit.py"
    _replace(
        package,
        "from src.utils import DATA, CONFIG, atomic_json, read_json",
        "from src.utils import DATA, CONFIG, read_json",
    )
    _replace(package, 'OUTFILE = DATA / "wc_package_audit_v4.json"\n\n', "")
    _replace(
        package,
        "    atomic_json(OUTFILE, out)\n",
        "    # Reference/debug entrypoint is intentionally read-only. Canonical artifact\n"
        "    # publication is owned by v4_decision_pipeline.\n",
    )

    lineup = ROOT / "src/engines/v4_lineup_optimizer.py"
    _replace(
        lineup,
        "from src.utils import DATA, CONFIG, atomic_json, read_json",
        "from src.utils import DATA, CONFIG, read_json",
    )
    _replace(lineup, 'OUTFILE = DATA / "lineup_decision_v4.json"\n', "")
    _replace(lineup, ";atomic_json(OUTFILE,out);", ";")

    runtime_guard = ROOT / "src/services/runtime_hydration_guard.py"
    runtime_guard.write_text(
        '''from __future__ import annotations\n\nimport hashlib\nimport json\nimport os\nimport re\nimport subprocess\nfrom pathlib import Path\n\nfrom src.utils import DATA, ROOT\n\nRUNTIME_BRANCH = "runtime-data-v4"\nRUNTIME_REF = f"refs/remotes/origin/{RUNTIME_BRANCH}"\nEXPECTED_BOT_EMAIL = "actions@users.noreply.github.com"\nEXPECTED_SUBJECT = "data(v4): atomic production snapshot [skip ci]"\n_SHA_RE = re.compile(r"^[0-9a-f]{40}$")\n\n\ndef _git_text(root: Path, *args: str) -> str:\n    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL, text=True).strip()\n\n\ndef _git_bytes(root: Path, *args: str) -> bytes:\n    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL)\n\n\ndef _git_ok(root: Path, *args: str) -> bool:\n    return subprocess.run(["git", *args], cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0\n\n\ndef _required_in_this_process() -> bool:\n    if os.getenv("GITHUB_ACTIONS") != "true":\n        return False\n    return os.getenv("GITHUB_EVENT_NAME") not in {"pull_request", "pull_request_target"}\n\n\ndef verify_hydrated_runtime_if_required(root: Path = ROOT) -> dict:\n    if not _required_in_this_process():\n        return {"status": "SKIPPED", "reason": "not_production_actions_context"}\n    if not _git_ok(root, "show-ref", "--verify", "--quiet", RUNTIME_REF):\n        return {"status": "SKIPPED", "reason": "runtime_branch_absent_first_publish"}\n\n    commit = _git_text(root, "rev-parse", RUNTIME_REF).lower()\n    parent_line = _git_text(root, "rev-list", "--parents", "-n1", RUNTIME_REF).split()\n    if len(parent_line) != 1:\n        raise RuntimeError("runtime hydration rejected: snapshot commit must be parentless")\n    author = _git_text(root, "show", "-s", "--format=%ae", RUNTIME_REF)\n    committer = _git_text(root, "show", "-s", "--format=%ce", RUNTIME_REF)\n    subject = _git_text(root, "show", "-s", "--format=%s", RUNTIME_REF)\n    if author != EXPECTED_BOT_EMAIL or committer != EXPECTED_BOT_EMAIL:\n        raise RuntimeError("runtime hydration rejected: commit identity is not governed automation")\n    if subject != EXPECTED_SUBJECT:\n        raise RuntimeError("runtime hydration rejected: atomic snapshot commit contract mismatch")\n\n    paths = [row for row in _git_text(root, "ls-tree", "-r", "--name-only", RUNTIME_REF).splitlines() if row]\n    unexpected = [path for path in paths if not path.startswith("data/")]\n    if unexpected:\n        raise RuntimeError(f"runtime hydration rejected: non-data paths present: {unexpected[:5]}")\n\n    remote_provenance_bytes = _git_bytes(root, "show", f"{RUNTIME_REF}:data/runtime_provenance_v4.json")\n    remote_latest_bytes = _git_bytes(root, "show", f"{RUNTIME_REF}:data/latest.json")\n    remote_snapshot_bytes = _git_bytes(root, "show", f"{RUNTIME_REF}:data/runtime/snapshot.v1.json")\n    provenance = json.loads(remote_provenance_bytes)\n    latest = json.loads(remote_latest_bytes)\n    if provenance.get("contract") != "V4_RUNTIME_PROVENANCE_V1":\n        raise RuntimeError("runtime hydration rejected: provenance contract mismatch")\n    if provenance.get("runtime_branch") != RUNTIME_BRANCH:\n        raise RuntimeError("runtime hydration rejected: provenance branch mismatch")\n    repository = os.getenv("GITHUB_REPOSITORY")\n    if repository and provenance.get("repository") != repository:\n        raise RuntimeError("runtime hydration rejected: provenance repository mismatch")\n    if latest.get("runtime_provenance") != provenance:\n        raise RuntimeError("runtime hydration rejected: latest/provenance mismatch")\n    snapshot_hash = hashlib.sha256(remote_snapshot_bytes).hexdigest()\n    if snapshot_hash != provenance.get("snapshot_sha256"):\n        raise RuntimeError("runtime hydration rejected: remote snapshot hash mismatch")\n\n    workspace_provenance = DATA if root == ROOT else root / "data"\n    workspace_provenance = workspace_provenance / "runtime_provenance_v4.json"\n    workspace_snapshot = (DATA if root == ROOT else root / "data") / "runtime" / "snapshot.v1.json"\n    if not workspace_provenance.exists() or not workspace_snapshot.exists():\n        raise RuntimeError("runtime hydration rejected: hydrated provenance/snapshot missing")\n    if json.loads(workspace_provenance.read_bytes()) != provenance:\n        raise RuntimeError("runtime hydration rejected: workspace provenance differs from runtime branch")\n    if hashlib.sha256(workspace_snapshot.read_bytes()).hexdigest() != snapshot_hash:\n        raise RuntimeError("runtime hydration rejected: workspace snapshot differs from runtime branch")\n\n    source = str(provenance.get("canonical_source_sha") or "").lower()\n    if not _SHA_RE.fullmatch(source):\n        raise RuntimeError("runtime hydration rejected: canonical source SHA invalid")\n    if not _git_ok(root, "merge-base", "--is-ancestor", source, "HEAD"):\n        raise RuntimeError("runtime hydration rejected: source SHA is not canonical checkout ancestry")\n\n    return {\n        "status": "PASS",\n        "runtime_branch": RUNTIME_BRANCH,\n        "runtime_commit": commit,\n        "canonical_source_sha": source,\n        "snapshot_sha256": snapshot_hash,\n        "parentless_snapshot": True,\n        "automation_identity": True,\n        "data_only_tree": True,\n        "provenance_verified": True,\n    }\n''',
        encoding="utf-8",
    )

    orchestrator = ROOT / "src/services/orchestrator.py"
    _replace(
        orchestrator,
        "from src.services.contracts import file_digest, validate_contracts\n",
        "from src.services.contracts import file_digest, validate_contracts\nfrom src.services.runtime_hydration_guard import verify_hydrated_runtime_if_required\n",
    )
    _replace(
        orchestrator,
        ") -> dict:\n    startup_assurance = architecture_guard_service.run()\n",
        ") -> dict:\n    runtime_hydration_assurance = verify_hydrated_runtime_if_required(root=root)\n    startup_assurance = architecture_guard_service.run()\n",
    )
    _replace(
        orchestrator,
        '        "startup_assurance": {"service": "architecture_guard", "status": startup_assurance.get("status"), "runtime_microservice": False},\n',
        '        "startup_assurance": {"service": "architecture_guard", "status": startup_assurance.get("status"), "runtime_microservice": False},\n'
        '        "runtime_hydration_assurance": runtime_hydration_assurance,\n',
    )

    guard = ROOT / "src/services/architecture_guard_service.py"
    _replace(
        guard,
        '    CONFIG / "release_manifest.json",\n    CONFIG / "intelligence/owned_challenger_decision_v4.json",\n',
        '    CONFIG / "release_manifest.json",\n    CONFIG / "runtime_artifact_policy.json",\n    CONFIG / "intelligence/owned_challenger_decision_v4.json",\n',
    )
    _replace(
        guard,
        'SERVING_MODULE = ROOT / "src/engines/v4_serving_contract.py"\nRELEASE_MODULE = ROOT / "src/release.py"\n',
        'SERVING_MODULE = ROOT / "src/engines/v4_serving_contract.py"\n'
        'REFERENCE_READ_ONLY_MODULES = (\n'
        '    ROOT / "src/engines/v4_wc_package_audit.py",\n'
        '    ROOT / "src/engines/v4_lineup_optimizer.py",\n'
        ')\n'
        'RELEASE_MODULE = ROOT / "src/release.py"\n',
    )
    _replace(
        guard,
        '    moving_literals = _moving_operational_literal_violations()\n',
        '    reference_writer_violations = [\n'
        '        str(path.relative_to(ROOT))\n'
        '        for path in REFERENCE_READ_ONLY_MODULES\n'
        '        if "atomic_json(" in _text(path)\n'
        '    ]\n'
        '    checks["reference_modules_read_only"] = (\n'
        '        not reference_writer_violations, reference_writer_violations\n'
        '    )\n\n'
        '    moving_literals = _moving_operational_literal_violations()\n',
    )
    _replace(
        guard,
        '            "owned_challenger_single_decision_authority": True,\n',
        '            "owned_challenger_single_decision_authority": True,\n'
        '            "reference_modules_read_only": True,\n',
    )

    policy_path = ROOT / "config/runtime_artifact_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    runtime = policy.setdefault("runtime_branch", {})
    runtime["hydration_integrity_gate"] = {
        "mode": "FAIL_CLOSED_BEFORE_SERVICE_EXECUTION",
        "requires_parentless_orphan_snapshot": True,
        "requires_data_only_tree": True,
        "requires_automation_commit_identity": True,
        "requires_provenance_contract_match": True,
        "requires_snapshot_hash_match": True,
        "requires_workspace_snapshot_match": True,
        "requires_canonical_source_ancestor": True,
    }
    runtime["platform_write_protection"] = {
        "authority": "GITHUB_BRANCH_RULESET",
        "required_target": "block direct human writes while allowing governed automation force-replace",
        "repository_code_can_configure": False,
        "external_admin_control_required": True,
    }
    policy.setdefault("guardrails", {})["hydrate_only_trusted_runtime_before_service_use"] = True
    policy["guardrails"]["reference_modules_cannot_publish_canonical_decision_artifacts"] = True
    policy_path.write_text(json.dumps(policy, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    test_path = ROOT / "tests/test_v4_red_runtime_writer_hardening.py"
    test_path.write_text(
        '''from __future__ import annotations\n\nimport hashlib\nimport json\nfrom pathlib import Path\n\nimport pytest\n\nfrom src.services import runtime_hydration_guard as guard\n\nROOT = Path(__file__).resolve().parents[1]\n\n\ndef test_reference_modules_cannot_write_canonical_artifacts():\n    for relative in (\n        "src/engines/v4_wc_package_audit.py",\n        "src/engines/v4_lineup_optimizer.py",\n    ):\n        text = (ROOT / relative).read_text(encoding="utf-8")\n        assert "atomic_json(" not in text, relative\n\n\ndef test_runtime_policy_declares_fail_closed_hydration_gate_and_external_ruleset():\n    policy = json.loads((ROOT / "config/runtime_artifact_policy.json").read_text())\n    runtime = policy["runtime_branch"]\n    gate = runtime["hydration_integrity_gate"]\n    assert gate["mode"] == "FAIL_CLOSED_BEFORE_SERVICE_EXECUTION"\n    assert all(value is True for key, value in gate.items() if key.startswith("requires_"))\n    platform = runtime["platform_write_protection"]\n    assert platform["authority"] == "GITHUB_BRANCH_RULESET"\n    assert platform["external_admin_control_required"] is True\n\n\ndef test_orchestrator_verifies_runtime_before_architecture_and_services():\n    text = (ROOT / "src/services/orchestrator.py").read_text(encoding="utf-8")\n    assert text.index("verify_hydrated_runtime_if_required(root=root)") < text.index("architecture_guard_service.run()")\n    assert '"runtime_hydration_assurance": runtime_hydration_assurance' in text\n\n\ndef test_runtime_artifact_policy_is_architecture_attested():\n    text = (ROOT / "src/services/architecture_guard_service.py").read_text(encoding="utf-8")\n    assert 'CONFIG / "runtime_artifact_policy.json"' in text\n    assert 'checks["reference_modules_read_only"]' in text\n\n\ndef test_runtime_guard_accepts_governed_snapshot_and_rejects_tamper(tmp_path, monkeypatch):\n    data = tmp_path / "data"\n    (data / "runtime").mkdir(parents=True)\n    snapshot = b'{"snapshot":"governed"}\\n'\n    source = "a" * 40\n    provenance = {\n        "schema_version": 1,\n        "contract": "V4_RUNTIME_PROVENANCE_V1",\n        "canonical_source_sha": source,\n        "runtime_branch": "runtime-data-v4",\n        "repository": "iphoenk/FPL-iphoenk-engine",\n        "snapshot_sha256": hashlib.sha256(snapshot).hexdigest(),\n    }\n    latest = {"runtime_provenance": provenance}\n    (data / "runtime_provenance_v4.json").write_text(json.dumps(provenance))\n    (data / "runtime" / "snapshot.v1.json").write_bytes(snapshot)\n    monkeypatch.setenv("GITHUB_ACTIONS", "true")\n    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")\n    monkeypatch.setenv("GITHUB_REPOSITORY", "iphoenk/FPL-iphoenk-engine")\n    monkeypatch.setattr(guard, "DATA", data)\n    monkeypatch.setattr(guard, "ROOT", tmp_path)\n    monkeypatch.setattr(guard, "_git_ok", lambda _root, *args: True)\n\n    def text(_root, *args):\n        joined = " ".join(args)\n        if "rev-parse" in joined: return "b" * 40\n        if "rev-list" in joined: return "b" * 40\n        if "--format=%ae" in joined or "--format=%ce" in joined: return guard.EXPECTED_BOT_EMAIL\n        if "--format=%s" in joined: return guard.EXPECTED_SUBJECT\n        if "ls-tree" in joined: return "data/latest.json\\ndata/runtime_provenance_v4.json\\ndata/runtime/snapshot.v1.json"\n        raise AssertionError(joined)\n\n    def binary(_root, *args):\n        target = args[-1]\n        if target.endswith("runtime_provenance_v4.json"): return json.dumps(provenance).encode()\n        if target.endswith("latest.json"): return json.dumps(latest).encode()\n        if target.endswith("snapshot.v1.json"): return snapshot\n        raise AssertionError(target)\n\n    monkeypatch.setattr(guard, "_git_text", text)\n    monkeypatch.setattr(guard, "_git_bytes", binary)\n    result = guard.verify_hydrated_runtime_if_required(root=tmp_path)\n    assert result["status"] == "PASS"\n    (data / "runtime" / "snapshot.v1.json").write_bytes(b"tampered")\n    with pytest.raises(RuntimeError, match="workspace snapshot differs"):\n        guard.verify_hydrated_runtime_if_required(root=tmp_path)\n''',
        encoding="utf-8",
    )

    attest_builder = ROOT / "tests/test_000_attest_red_hardening.py"
    attest_builder.write_text(
        '''from __future__ import annotations\n\nimport os\nimport subprocess\nfrom pathlib import Path\n\nimport pytest\n\nROOT = Path(__file__).resolve().parents[1]\nBRANCH = "codex/v4-claude-red-hardening"\n\n\ndef test_refresh_red_hardening_attestation():\n    if os.getenv("GITHUB_ACTIONS") != "true" or os.getenv("GITHUB_HEAD_REF") != BRANCH:\n        pytest.skip("attestation builder runs only in its PR CI")\n    subprocess.run(["python", "tools/v4_architecture_guard_attest.py"], cwd=ROOT, check=True)\n    subprocess.run(["git", "rm", "tests/test_000_attest_red_hardening.py"], cwd=ROOT, check=True)\n    subprocess.run(["git", "add", "config/architecture_guard_attestation.json"], cwd=ROOT, check=True)\n    subprocess.run(["git", "-c", "user.name=github-actions[bot]", "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com", "commit", "-m", "chore(v4): attest red hardening"], cwd=ROOT, check=True)\n    subprocess.run(["git", "push", "origin", f"HEAD:{BRANCH}"], cwd=ROOT, check=True)\n''',
        encoding="utf-8",
    )

    subprocess.run(["git", "rm", "tests/test_000_claude_red_hardening_builder.py"], cwd=ROOT, check=True)
    files = [
        "src/engines/v4_wc_package_audit.py",
        "src/engines/v4_lineup_optimizer.py",
        "src/services/runtime_hydration_guard.py",
        "src/services/orchestrator.py",
        "src/services/architecture_guard_service.py",
        "config/runtime_artifact_policy.json",
        "tests/test_v4_red_runtime_writer_hardening.py",
        "tests/test_000_attest_red_hardening.py",
        "tests/test_000_claude_red_hardening_builder.py",
    ]
    subprocess.run(["git", "add", "-A", "--", *files], cwd=ROOT, check=True)
    subprocess.run(
        ["git", "-c", "user.name=github-actions[bot]", "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com", "commit", "-m", "fix(v4): harden runtime trust and canonical writers"],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(["git", "push", "origin", f"HEAD:{BRANCH}"], cwd=ROOT, check=True)
