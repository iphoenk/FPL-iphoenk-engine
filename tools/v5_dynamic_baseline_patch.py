from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = "runtime-data:data/runtime_manifest.json#source_commit"
ENV = "V5_PRODUCTION_SOURCE_SHA"


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def write(path: str, value: dict) -> None:
    (ROOT / path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def patch_metadata() -> None:
    manifest = load("config/v5_convergence_manifest.json")
    baseline = manifest["baselines"]
    baseline.pop("production_main_sha", None)
    baseline.pop("production_code_commit", None)
    baseline["production_source_authority"] = AUTHORITY
    baseline["production_source_environment"] = ENV
    manifest["operational_acceptance_evidence"]["superseded_evidence"]["reason"] = (
        "Previous validated REAL_SHADOW evidence belongs to a superseded release identity. "
        "The deployed production source is resolved at runtime from runtime-data and any material V5 release or production semantic change requires fresh exact-identity validation."
    )
    manifest["operational_acceptance_evidence"]["note"] = (
        f"Runtime acceptance authority is {manifest['operational_acceptance_evidence']['authority']}. "
        f"Production source authority is {AUTHORITY}; static deployment SHAs are forbidden."
    )
    manifest["production_promotion"]["reason"] = (
        "Operational evidence is resolved from the canonical shadow acceptance summary and production source is resolved dynamically from runtime-data. "
        "Prediction acceptance remains independent and mandatory."
    )
    write("config/v5_convergence_manifest.json", manifest)

    acceptance = load("config/v5_acceptance_registry.json")
    convergence = acceptance["convergence"]
    convergence.pop("production_main_sha", None)
    convergence.pop("production_code_commit", None)
    convergence["production_source_authority"] = AUTHORITY
    convergence["production_source_environment"] = ENV
    write("config/v5_acceptance_registry.json", acceptance)

    parity = load("config/v5_capability_parity_registry.json")
    authorities = parity["authorities"]
    authorities.pop("current_production_code_commit", None)
    authorities["current_production_runtime"] = f"deployed@{AUTHORITY}"
    authorities["current_production_code_commit_authority"] = AUTHORITY
    reanchor = parity["current_production_reanchor"]
    reanchor.pop("production_main_sha", None)
    reanchor.pop("production_code_commit", None)
    reanchor["production_source_authority"] = AUTHORITY
    reanchor["production_source_environment"] = ENV
    write("config/v5_capability_parity_registry.json", parity)

    status = load("IMPLEMENTATION_STATUS.json")
    production = status["production_authority"]
    production.pop("main_sha", None)
    production["source_commit_authority"] = AUTHORITY
    production["source_commit_environment"] = ENV
    status["notes"] = [
        line for line in status.get("notes") or []
        if "deployed production is now" not in str(line).lower() and "acceptance baseline is the sha" not in str(line).lower()
    ]
    status["notes"].append(
        f"Deployed production source is resolved dynamically from {AUTHORITY}; V5 metadata must not pin a mutable production SHA."
    )
    write("IMPLEMENTATION_STATUS.json", status)


def write_baseline_module() -> None:
    content = f'''from __future__ import annotations\n\nimport os\nimport re\nfrom typing import Any\n\nfrom src.v5.config_cache import load_json_config\n\nMANIFEST_CONFIG = "config/v5_convergence_manifest.json"\nPRODUCTION_SOURCE_AUTHORITY = "{AUTHORITY}"\nPRODUCTION_SOURCE_ENV = "{ENV}"\n_SHA40 = re.compile(r"^[0-9a-f]{{40}}$")\n\n\ndef production_source_contract() -> dict[str, Any]:\n    baseline = load_json_config(MANIFEST_CONFIG).get("baselines") or {{}}\n    authority = str(baseline.get("production_source_authority") or "")\n    environment = str(baseline.get("production_source_environment") or "")\n    if authority != PRODUCTION_SOURCE_AUTHORITY:\n        raise RuntimeError(f"unexpected V5 production source authority: {{authority}}")\n    if environment != PRODUCTION_SOURCE_ENV:\n        raise RuntimeError(f"unexpected V5 production source environment: {{environment}}")\n    if baseline.get("production_main_sha") is not None or baseline.get("production_code_commit") is not None:\n        raise RuntimeError("mutable deployed production SHA must not be pinned in V5 static metadata")\n    return {{"authority": authority, "environment": environment}}\n\n\ndef production_source_sha(explicit: str | None = None) -> str:\n    production_source_contract()\n    value = str(explicit if explicit is not None else os.getenv(PRODUCTION_SOURCE_ENV, "")).strip().lower()\n    if not _SHA40.fullmatch(value):\n        raise RuntimeError(\n            f"{{PRODUCTION_SOURCE_ENV}} must contain the exact 40-hex deployed runtime source_commit resolved from {{PRODUCTION_SOURCE_AUTHORITY}}"\n        )\n    return value\n'''
    (ROOT / "src/v5/production_baseline.py").write_text(content, encoding="utf-8")


def patch_release_attestation() -> None:
    path = ROOT / "src/v5/release_attestation.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "from src.v5.release_integrity import runtime_fingerprint\n",
        "from src.v5.release_integrity import runtime_fingerprint\nfrom src.v5.production_baseline import production_source_sha\n",
    )
    old = 'payload={"contract":cfg.get("contract"),"v5_version":V5_VERSION,"production_baseline_version":baseline.get("production_truth"),"production_main_sha":baseline.get("production_main_sha"),"runtime_release_fingerprint":release.get("fingerprint")} '
    if old not in text:
        old = 'payload={"contract":cfg.get("contract"),"v5_version":V5_VERSION,"production_baseline_version":baseline.get("production_truth"),"production_main_sha":baseline.get("production_main_sha"),"runtime_release_fingerprint":release.get("fingerprint")}\n'
    replacement = 'payload={"contract":cfg.get("contract"),"v5_version":V5_VERSION,"production_baseline_version":baseline.get("production_truth"),"production_main_sha":production_source_sha(),"runtime_release_fingerprint":release.get("fingerprint")}\n'
    if old not in text:
        raise RuntimeError("release attestation payload drifted")
    text = text.replace(old, replacement, 1)
    path.write_text(text, encoding="utf-8")


def patch_shadow_acceptance() -> None:
    path = ROOT / "src/v5/shadow_acceptance.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "from src.v5.release_integrity import runtime_fingerprint\n",
        "from src.v5.release_integrity import runtime_fingerprint\nfrom src.v5.production_baseline import production_source_sha\n",
    )
    old = '''def _baseline() -> tuple[str, str]:\n    baseline = load_json_config(MANIFEST_CONFIG).get("baselines") or {}\n    return str(baseline.get("production_truth") or ""), str(baseline.get("production_main_sha") or "")\n'''
    new = '''def _baseline() -> tuple[str, str]:\n    baseline = load_json_config(MANIFEST_CONFIG).get("baselines") or {}\n    return str(baseline.get("production_truth") or ""), production_source_sha()\n'''
    if old not in text:
        raise RuntimeError("shadow acceptance baseline helper drifted")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_acceptance() -> None:
    path = ROOT / "src/v5/acceptance.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "from src.v5.release_attestation import release_attestation\n",
        "from src.v5.release_attestation import release_attestation\nfrom src.v5.production_baseline import PRODUCTION_SOURCE_AUTHORITY, production_source_contract, production_source_sha\n",
    )
    text = text.replace(
        '    baseline_sha = str(convergence.get("production_main_sha") or "")\n',
        '    baseline_sha = production_source_sha()\n    source_contract = production_source_contract()\n',
        1,
    )
    old = 'AcceptanceCheck("production_baseline_declared", manifest_baselines.get("production_truth") == baseline and manifest_baselines.get("production_main_sha") == baseline_sha and bool(baseline_sha), Plane.TRUTH, "football-truth baseline and current production runtime SHA are registry-driven and consistent"),'
    new = 'AcceptanceCheck("production_baseline_declared", manifest_baselines.get("production_truth") == baseline and manifest_baselines.get("production_source_authority") == PRODUCTION_SOURCE_AUTHORITY and convergence.get("production_source_authority") == PRODUCTION_SOURCE_AUTHORITY and source_contract.get("authority") == PRODUCTION_SOURCE_AUTHORITY and bool(baseline_sha), Plane.TRUTH, "football-truth baseline is static while deployed production source is runtime-manifest authoritative"),'
    if old not in text:
        raise RuntimeError("bootstrap acceptance production baseline check drifted")
    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")


def patch_unified_gate() -> None:
    path = ROOT / ".github/workflows/v5-unified-gate.yml"
    text = path.read_text(encoding="utf-8")
    old = '''          EXPECTED=$(python -c "import json; print(json.load(open('config/v5_convergence_manifest.json'))['baselines']['production_main_sha'])")\n          MAIN_HEAD=$(git rev-parse origin/main)\n          RUNTIME_SOURCE=$(git show origin/runtime-data:data/runtime_manifest.json | python -c "import json,sys; print(json.load(sys.stdin)['source_commit'])")\n          echo "accepted_deployed=$EXPECTED runtime_source=$RUNTIME_SOURCE repository_main=$MAIN_HEAD"\n          test "$EXPECTED" = "$RUNTIME_SOURCE"\n          git merge-base --is-ancestor "$EXPECTED" origin/main\n          if [ "$EXPECTED" != "$MAIN_HEAD" ]; then\n            echo "Repository main is ahead of deployed production; V5 remains anchored to the actually deployed runtime until runtime-data advances."\n          fi\n'''
    new = '''          AUTHORITY=$(python -c "import json; print(json.load(open('config/v5_convergence_manifest.json'))['baselines']['production_source_authority'])")\n          test "$AUTHORITY" = "runtime-data:data/runtime_manifest.json#source_commit"\n          MAIN_HEAD=$(git rev-parse origin/main)\n          RUNTIME_SOURCE=$(git show origin/runtime-data:data/runtime_manifest.json | python -c "import json,sys; print(json.load(sys.stdin)['source_commit'])")\n          [[ "$RUNTIME_SOURCE" =~ ^[0-9a-f]{40}$ ]]\n          git cat-file -e "${RUNTIME_SOURCE}^{commit}"\n          git merge-base --is-ancestor "$RUNTIME_SOURCE" origin/main\n          echo "V5_PRODUCTION_SOURCE_SHA=$RUNTIME_SOURCE" >> "$GITHUB_ENV"\n          echo "deployed_runtime_source=$RUNTIME_SOURCE repository_main=$MAIN_HEAD authority=$AUTHORITY"\n'''
    if old not in text:
        raise RuntimeError("unified gate baseline block drifted")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_shadow_workflow() -> None:
    path = ROOT / ".github/workflows/v5-shadow-cycle.yml"
    text = path.read_text(encoding="utf-8")
    old = '''      - name: Resolve accepted production baseline\n        shell: bash\n        run: |\n          set -euo pipefail\n          BASELINE_SHA=$(python -c "import json; print(json.load(open('config/v5_convergence_manifest.json'))['baselines']['production_main_sha'])")\n          TRUTH_BASELINE=$(python -c "import json; print(json.load(open('config/v5_convergence_manifest.json'))['baselines']['production_truth'])")\n          RUNTIME_LABEL=$(python -c "import json; print(json.load(open('config/v5_convergence_manifest.json'))['baselines']['production_runtime'])")\n          TEAM_ID=$(python -c "import json; print(json.load(open('config/engine.json'))['team_id'])")\n          echo "V3_SOURCE_SHA=$BASELINE_SHA" >> "$GITHUB_ENV"\n          echo "V3_TRUTH_BASELINE=$TRUTH_BASELINE" >> "$GITHUB_ENV"\n          echo "V3_RUNTIME_LABEL=$RUNTIME_LABEL" >> "$GITHUB_ENV"\n          echo "FPL_TEAM_ID=$TEAM_ID" >> "$GITHUB_ENV"\n          echo "accepted_truth=$TRUTH_BASELINE runtime=$RUNTIME_LABEL sha=$BASELINE_SHA team_id=$TEAM_ID"\n'''
    new = '''      - name: Resolve deployed production baseline\n        shell: bash\n        run: |\n          set -euo pipefail\n          git fetch origin "$V3_SOURCE_BRANCH" "$V3_RUNTIME_BRANCH" --quiet\n          AUTHORITY=$(python -c "import json; print(json.load(open('config/v5_convergence_manifest.json'))['baselines']['production_source_authority'])")\n          test "$AUTHORITY" = "runtime-data:data/runtime_manifest.json#source_commit"\n          BASELINE_SHA=$(git show "origin/${V3_RUNTIME_BRANCH}:data/runtime_manifest.json" | python -c "import json,sys; print(json.load(sys.stdin)['source_commit'])")\n          [[ "$BASELINE_SHA" =~ ^[0-9a-f]{40}$ ]]\n          git cat-file -e "${BASELINE_SHA}^{commit}"\n          git merge-base --is-ancestor "$BASELINE_SHA" "origin/$V3_SOURCE_BRANCH"\n          TRUTH_BASELINE=$(python -c "import json; print(json.load(open('config/v5_convergence_manifest.json'))['baselines']['production_truth'])")\n          RUNTIME_LABEL=$(python -c "import json; print(json.load(open('config/v5_convergence_manifest.json'))['baselines']['production_runtime'])")\n          TEAM_ID=$(python -c "import json; print(json.load(open('config/engine.json'))['team_id'])")\n          echo "V3_SOURCE_SHA=$BASELINE_SHA" >> "$GITHUB_ENV"\n          echo "V5_PRODUCTION_SOURCE_SHA=$BASELINE_SHA" >> "$GITHUB_ENV"\n          echo "V3_TRUTH_BASELINE=$TRUTH_BASELINE" >> "$GITHUB_ENV"\n          echo "V3_RUNTIME_LABEL=$RUNTIME_LABEL" >> "$GITHUB_ENV"\n          echo "FPL_TEAM_ID=$TEAM_ID" >> "$GITHUB_ENV"\n          echo "accepted_truth=$TRUTH_BASELINE runtime=$RUNTIME_LABEL deployed_sha=$BASELINE_SHA team_id=$TEAM_ID"\n'''
    if old not in text:
        raise RuntimeError("shadow resolve block drifted")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_scheduler_gate() -> None:
    path = ROOT / "scripts/v5_evidence_scheduler_gate.py"
    text = path.read_text(encoding="utf-8")
    old = '''    manifest = json.loads(Path("config/v5_convergence_manifest.json").read_text(encoding="utf-8"))\n    expected_runtime_sha = str((manifest.get("baselines") or {}).get("production_main_sha") or "")\n    repository_main_sha = git("rev-parse", "origin/main")\n    runtime_manifest = load_remote_json(f"origin/{v3_runtime_branch}", "data/runtime_manifest.json")\n    deployed_runtime_sha = str(runtime_manifest.get("source_commit") or "")\n    ancestor_ok = bool(expected_runtime_sha) and subprocess.run(\n        ["git", "merge-base", "--is-ancestor", expected_runtime_sha, "origin/main"],\n        check=False,\n    ).returncode == 0\n    baseline_ready = bool(expected_runtime_sha and expected_runtime_sha == deployed_runtime_sha and ancestor_ok)\n    details = {\n        "accepted_deployed_runtime_sha": expected_runtime_sha,\n        "deployed_runtime_sha": deployed_runtime_sha,\n        "repository_main_sha": repository_main_sha,\n        "accepted_runtime_is_ancestor_of_main": ancestor_ok,\n        "baseline_ready": baseline_ready,\n    }\n'''
    new = '''    manifest = json.loads(Path("config/v5_convergence_manifest.json").read_text(encoding="utf-8"))\n    authority = str((manifest.get("baselines") or {}).get("production_source_authority") or "")\n    repository_main_sha = git("rev-parse", "origin/main")\n    runtime_manifest = load_remote_json(f"origin/{v3_runtime_branch}", "data/runtime_manifest.json")\n    deployed_runtime_sha = str(runtime_manifest.get("source_commit") or "").lower()\n    sha_valid = bool(re.fullmatch(r"[0-9a-f]{40}", deployed_runtime_sha))\n    ancestor_ok = sha_valid and subprocess.run(\n        ["git", "merge-base", "--is-ancestor", deployed_runtime_sha, "origin/main"],\n        check=False,\n    ).returncode == 0\n    baseline_ready = bool(authority == "runtime-data:data/runtime_manifest.json#source_commit" and sha_valid and ancestor_ok)\n    details = {\n        "production_source_authority": authority,\n        "deployed_runtime_sha": deployed_runtime_sha,\n        "repository_main_sha": repository_main_sha,\n        "deployed_runtime_is_ancestor_of_main": ancestor_ok,\n        "baseline_ready": baseline_ready,\n    }\n'''
    if old not in text:
        raise RuntimeError("scheduler dynamic baseline block drifted")
    text = text.replace("import os\n", "import os\nimport re\n", 1)
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_release_test() -> None:
    path = ROOT / "tests/test_v5_release_attestation.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace("def test_release_attestation_binds_current_candidate():\n", "def test_release_attestation_binds_current_candidate(monkeypatch):\n    deployed = \"a\" * 40\n    monkeypatch.setenv(\"V5_PRODUCTION_SOURCE_SHA\", deployed)\n    release_attestation.cache_clear()\n", 1)
    text = text.replace('    assert row["production_main_sha"] == manifest["baselines"]["production_main_sha"]\n', '    assert row["production_main_sha"] == deployed\n    assert manifest["baselines"]["production_source_authority"] == "runtime-data:data/runtime_manifest.json#source_commit"\n    assert "production_main_sha" not in manifest["baselines"]\n')
    path.write_text(text, encoding="utf-8")


def patch_current_parity_test() -> None:
    path = ROOT / "tests/test_v5_current_v3_parity.py"
    text = path.read_text(encoding="utf-8")
    start = text.index("def test_current_production_reanchor_is_exact_and_keeps_frozen_truth_baseline():")
    end = text.index("\ndef test_current_v3_control_plane_is_reconciled_without_duplicate_v5_execution_truth():", start)
    new = '''def test_current_production_reanchor_is_runtime_manifest_authoritative_and_keeps_frozen_truth_baseline(monkeypatch):\n    from src.v5.production_baseline import production_source_sha\n\n    manifest = _load("config/v5_convergence_manifest.json")\n    acceptance = _load("config/v5_acceptance_registry.json")\n    parity = _load("config/v5_capability_parity_registry.json")\n    status = _load("IMPLEMENTATION_STATUS.json")\n    authority = "runtime-data:data/runtime_manifest.json#source_commit"\n    deployed_sha = "b" * 40\n    monkeypatch.setenv("V5_PRODUCTION_SOURCE_SHA", deployed_sha)\n\n    assert production_source_sha() == deployed_sha\n    assert manifest["baselines"]["production_truth"] == "v3.20.0"\n    assert manifest["baselines"]["production_source_authority"] == authority\n    assert manifest["baselines"]["production_source_environment"] == "V5_PRODUCTION_SOURCE_SHA"\n    assert "production_main_sha" not in manifest["baselines"]\n    assert "production_code_commit" not in manifest["baselines"]\n    assert acceptance["convergence"]["production_source_authority"] == authority\n    assert "production_main_sha" not in acceptance["convergence"]\n    assert parity["current_production_reanchor"]["production_source_authority"] == authority\n    assert parity["authorities"]["current_production_code_commit_authority"] == authority\n    assert status["production_authority"]["source_commit_authority"] == authority\n    assert manifest["baselines"]["production_runtime_schema_version"] == 49\n    assert manifest["baselines"]["production_execution_registry"] == "V3_EXECUTION_DOMAINS_V2"\n    assert manifest["baselines"]["production_compiled_plan_registry"] == COMPILED_PLAN\n    assert manifest["baselines"]["production_compiled_plan_sha256"] == COMPILED_PLAN_SHA\n    assert manifest["baselines"]["production_capability_telemetry_registry"] == "V3_CAPABILITY_TELEMETRY_V1"\n\n    topology = parity["current_production_reanchor"]["v3_topology"]\n    assert topology["compiled_plan_registry"] == COMPILED_PLAN\n    assert topology["compiled_plan_sha256"] == COMPILED_PLAN_SHA\n    assert topology["capability_telemetry_registry"] == "V3_CAPABILITY_TELEMETRY_V1"\n    assert topology["sub3s_fast_lane_runtime_hardening_only"] is True\n    assert topology["semantic_prediction_reuse_runtime_hardening_only"] is True\n    assert topology["gameweek_lifecycle_reporting_hardening_only"] is True\n    assert topology["bounded_warm_retry_runtime_workflow_hardening_only"] is True\n    assert topology["official_phase_independent_fetch_overlap_runtime_hardening_only"] is True\n    assert topology["authenticated_official_production_readiness_runtime_hardening_only"] is True\n    assert topology["fingerprint_only_prediction_reuse_runtime_hardening_only"] is True\n    assert topology["public_mini_league_membership_reporting_only"] is True\n    assert parity["governance"]["reanchor_requires_full_v5_gate"] is True\n    assert parity["governance"]["reanchor_does_not_change_frozen_football_truth_baseline"] is True\n    assert parity["governance"]["reanchor_binds_to_deployed_runtime_not_unpublished_main_head"] is True\n    assert parity["governance"]["deployed_runtime_must_be_ancestor_of_main"] is True\n\n'''
    path.write_text(text[:start] + new + text[end+1:], encoding="utf-8")


def patch_metadata_test() -> None:
    path = ROOT / "tests/test_v5_metadata_authority_hygiene.py"
    text = path.read_text(encoding="utf-8")
    text = re.sub(r'DEPLOYED_SHA = "[0-9a-f]{40}"\nSTALE_DEPLOYED_SHAS = \{.*?\}\n', '', text, count=1, flags=re.S)
    text = text.replace(
        '    assert status["production_authority"]["main_sha"] == manifest["baselines"]["production_main_sha"]\n',
        '    assert status["production_authority"]["source_commit_authority"] == manifest["baselines"]["production_source_authority"]\n',
        1,
    )
    start = text.index("def test_owned_metadata_is_reanchored_to_the_one_deployed_runtime_sha():")
    end = text.index("\ndef test_predeadline_governance_is_public_official_plus_scoped_capture_only():", start)
    new = '''def test_owned_metadata_uses_runtime_manifest_source_authority_without_mutable_sha_pin():\n    manifest = _load("config/v5_convergence_manifest.json")\n    acceptance = _load("config/v5_acceptance_registry.json")\n    parity = _load("config/v5_capability_parity_registry.json")\n    status = _load("IMPLEMENTATION_STATUS.json")\n    authority = "runtime-data:data/runtime_manifest.json#source_commit"\n\n    assert manifest["baselines"]["production_source_authority"] == authority\n    assert acceptance["convergence"]["production_source_authority"] == authority\n    assert parity["authorities"]["current_production_code_commit_authority"] == authority\n    assert parity["current_production_reanchor"]["production_source_authority"] == authority\n    assert status["production_authority"]["source_commit_authority"] == authority\n    assert "production_main_sha" not in manifest["baselines"]\n    assert "production_code_commit" not in manifest["baselines"]\n    assert "production_main_sha" not in acceptance["convergence"]\n    assert "production_code_commit" not in acceptance["convergence"]\n    assert "production_main_sha" not in parity["current_production_reanchor"]\n    assert "production_code_commit" not in parity["current_production_reanchor"]\n    assert "main_sha" not in status["production_authority"]\n\n    assert manifest["baselines"]["production_truth"] == "v3.20.0"\n    assert acceptance["convergence"]["production_baseline"] == "v3.20.0"\n    assert parity["authorities"]["football_truth_baseline"] == "v3.20.0"\n    assert manifest["advanced_v5"]["v3_atomic_runtime_publication_reconciled_as_runtime_governance_hardening"] is True\n    assert acceptance["convergence"]["v3_atomic_runtime_publication_reconciled_as_runtime_governance_hardening"] is True\n    assert parity["current_production_reanchor"]["v3_topology"]["atomic_runtime_publication_runtime_governance_only"] is True\n    assert manifest["advanced_v5"]["v3_structured_user_capture_authority_reconciled_without_v5_auth_authority_change"] is True\n    assert acceptance["convergence"]["v3_structured_user_capture_authority_reconciled_without_v5_auth_authority_change"] is True\n    assert parity["current_production_reanchor"]["v3_topology"]["structured_user_capture_phase_authority_governance_only"] is True\n\n'''
    path.write_text(text[:start] + new + text[end+1:], encoding="utf-8")


def patch_operational_manifest_test() -> None:
    path = ROOT / "tests/test_v5_operational_acceptance_manifest.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace('    deployed_sha = manifest["baselines"]["production_main_sha"]\n', '    authority = manifest["baselines"]["production_source_authority"]\n')
    text = text.replace('    assert deployed_sha in old["reason"]\n', '    assert authority == "runtime-data:data/runtime_manifest.json#source_commit"\n    assert "runtime" in old["reason"].lower()\n')
    text = text.replace('    assert "0/3" in old["reason"]\n', '')
    path.write_text(text, encoding="utf-8")


def patch_control_plane_test() -> None:
    path = ROOT / "tests/test_v5_control_plane_governance.py"
    text = path.read_text(encoding="utf-8")
    insert = '''\n\ndef test_production_source_is_runtime_manifest_authority_not_static_sha():\n    manifest = _load("config/v5_convergence_manifest.json")\n    acceptance = _load("config/v5_acceptance_registry.json")\n    baseline = manifest["baselines"]\n    assert baseline["production_source_authority"] == "runtime-data:data/runtime_manifest.json#source_commit"\n    assert baseline["production_source_environment"] == "V5_PRODUCTION_SOURCE_SHA"\n    assert "production_main_sha" not in baseline\n    assert "production_code_commit" not in baseline\n    assert acceptance["convergence"]["production_source_authority"] == baseline["production_source_authority"]\n'''
    text += insert
    text = text.replace('    assert "production_main_sha" in gate\n', '    assert "production_source_authority" in gate\n')
    path.write_text(text, encoding="utf-8")


def patch_prediction_baseline_test() -> None:
    path = ROOT / "tests/test_v5_prediction_baseline_provenance.py"
    text = path.read_text(encoding="utf-8")
    old = '        expected_sha = json.loads(Path("config/v5_convergence_manifest.json").read_text(encoding="utf-8"))["baselines"]["production_main_sha"]\n'
    new = '        from src.v5.production_baseline import production_source_sha\n        expected_sha = production_source_sha()\n'
    text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


def write_baseline_tests() -> None:
    content = '''import pytest\n\nfrom src.v5.production_baseline import production_source_contract, production_source_sha\n\n\ndef test_production_source_contract_is_runtime_manifest_authoritative():\n    row = production_source_contract()\n    assert row == {\n        "authority": "runtime-data:data/runtime_manifest.json#source_commit",\n        "environment": "V5_PRODUCTION_SOURCE_SHA",\n    }\n\n\ndef test_production_source_sha_requires_exact_40_hex(monkeypatch):\n    monkeypatch.delenv("V5_PRODUCTION_SOURCE_SHA", raising=False)\n    with pytest.raises(RuntimeError):\n        production_source_sha()\n    monkeypatch.setenv("V5_PRODUCTION_SOURCE_SHA", "abc123")\n    with pytest.raises(RuntimeError):\n        production_source_sha()\n    monkeypatch.setenv("V5_PRODUCTION_SOURCE_SHA", "C" * 40)\n    assert production_source_sha() == "c" * 40\n'''
    (ROOT / "tests/test_v5_production_baseline.py").write_text(content, encoding="utf-8")


def main() -> None:
    patch_metadata()
    write_baseline_module()
    patch_release_attestation()
    patch_shadow_acceptance()
    patch_acceptance()
    patch_unified_gate()
    patch_shadow_workflow()
    patch_scheduler_gate()
    patch_release_test()
    patch_current_parity_test()
    patch_metadata_test()
    patch_operational_manifest_test()
    patch_control_plane_test()
    patch_prediction_baseline_test()
    write_baseline_tests()


if __name__ == "__main__":
    main()
