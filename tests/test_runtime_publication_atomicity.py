from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.runtime_v3.publication_verify import verify_publication
from src.runtime_v3.publish_snapshot import PUBLIC_AUTH_PROJECTION, materialize


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "v3-runtime.yml"


def _write_snapshot(
    data_dir: Path,
    payloads: dict[str, object],
    *,
    source_commit: str = "a" * 40,
    profile: str = "fast_decision",
) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    payload_bytes = 0
    for relative, payload in payloads.items():
        path = data_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, sort_keys=True) + "\n"
        path.write_text(text, encoding="utf-8")
        payload_bytes += path.stat().st_size

    paths = sorted(payloads)
    manifest = {
        "registry": "RUNTIME_MANIFEST_V1",
        "schema_version": 1,
        "source_commit": source_commit,
        "execution_profile": profile,
        "publication": {
            "paths": paths,
            "file_count_without_manifest": len(paths),
            "bytes_without_manifest": payload_bytes,
            "file_count": len(paths) + 1,
        },
    }
    (data_dir / "runtime_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_runtime_workflow_orders_every_candidate_gate_before_publication() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    ordered_markers = [
        "Run governed canonical domain execution profile",
        "Validate production decision contracts",
        "Enforce selected profile runtime SLO with one bounded warm retry",
        "Verify V3 candidate definition of done before publication",
        "Materialize and validate publication whitelist",
        "Transfer verified runtime snapshot to isolated publisher",
        "Assert source main is still canonical before publication",
        "Revalidate transferred publication artifact",
        "Publish rolling runtime snapshot atomically",
        "Verify published runtime provenance and exact whitelist",
    ]
    positions = [text.index(marker) for marker in ordered_markers]
    assert positions == sorted(positions)

    assert "--scope candidate" in text
    assert "--scope production" not in text
    assert "cancel-in-progress: false" in text
    assert "needs: compute" in text


def test_runtime_publication_uses_exact_source_and_branch_leases() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "SOURCE_COMMIT:" in text
    assert 'canonical_main="$(git rev-parse refs/remotes/origin/main)"' in text
    assert 'if [ "$canonical_main" != "$SOURCE_COMMIT" ]; then' in text
    assert '--source-commit "$SOURCE_COMMIT"' in text
    assert '--force-with-lease="refs/heads/${RUNTIME_BRANCH}:${RUNTIME_BASE_SHA}"' in text
    assert "git push --force origin" not in text
    assert 'if [ "$published_head" != "$PUBLISHED_RUNTIME_SHA" ]; then' in text
    assert 'diff -qr "$RUNNER_TEMP/runtime-publish/data" "$verify_tree/data"' in text


def test_publication_registry_forbids_derived_private_auth_state() -> None:
    registry = json.loads((ROOT / "config" / "runtime" / "runtime_publish_registry.json").read_text())
    policy = registry["policy"]
    assert policy["raw_authenticated_payloads_are_forbidden"] is True
    assert policy["derived_private_authenticated_fields_are_forbidden_in_publication"] is True
    assert policy["public_authenticated_state_is_health_projection_only"] is True


def test_publication_verifier_accepts_declared_exact_manifest(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    source_commit = "1" * 40
    _write_snapshot(data_dir, {"latest.json": {"status": "ok"}}, source_commit=source_commit)

    result = verify_publication(
        data_dir,
        source_commit=source_commit,
        profile="fast_decision",
    )

    assert result["status"] == "PASS"
    assert result["unauthorized_paths"] == []
    assert result["source_commit"] == source_commit


def test_publication_verifier_rejects_undeclared_artifact(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _write_snapshot(data_dir, {"latest.json": {"status": "ok"}})
    (data_dir / "raw-session.txt").write_text("forbidden\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="unauthorized runtime publication paths"):
        verify_publication(data_dir, source_commit="a" * 40, profile="fast_decision")


def test_publication_verifier_rejects_raw_authenticated_payload_claim(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _write_snapshot(
        data_dir,
        {
            "auth.json": {
                "state": "VALID",
                "raw_authenticated_payload_persisted": True,
            }
        },
    )

    with pytest.raises(RuntimeError, match="raw authenticated payloads are excluded"):
        verify_publication(data_dir, source_commit="a" * 40, profile="fast_decision")


def test_publication_verifier_rejects_derived_private_authenticated_fields(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    public = {
        "public_projection": PUBLIC_AUTH_PROJECTION,
        "state": "VALID",
        "raw_authenticated_payload_persisted": False,
        "safe_finance": {"bank": 10, "prices_for_private_squad": [{"element": 1, "selling_price": 50}]},
    }
    _write_snapshot(data_dir, {"auth.json": public})

    with pytest.raises(RuntimeError, match="non-public authenticated fields"):
        verify_publication(data_dir, source_commit="a" * 40, profile="fast_decision")


def test_materialization_projects_private_auth_in_auth_and_latest_only(tmp_path: Path) -> None:
    source = tmp_path / "source"
    output = tmp_path / "publish"
    source.mkdir()
    private_auth = {
        "checked_at": "2026-09-01T00:00:00+00:00",
        "expected_entry": 3462711,
        "state": "VALID",
        "mode": "session_cookie",
        "verified_entry": 3462711,
        "endpoint_health": {"my_team": {"status": "LIVE"}},
        "safe_finance": {
            "bank": 10,
            "private_exact_sell_total": 1000,
            "prices_for_private_squad": [{"element": 1, "purchase_price": 50, "selling_price": 51}],
        },
        "draft_integrity": {"count": 15, "fingerprint": "private-fingerprint"},
        "chip_state": {"available": True, "chips": [{"name": "wildcard"}]},
        "transfers_latest": {"available": True, "count": 2},
        "raw_authenticated_payload_persisted": False,
        "production_readiness": {"required": False, "ready": True, "status": "AVAILABLE", "reasons": []},
        "enhancement_health": {"required": False, "ready": True, "status": "AVAILABLE", "reasons": []},
        "policy": {"role": "OPTIONAL_PRIVATE_ENRICHMENT", "production_blocking": False},
    }
    (source / "auth.json").write_text(json.dumps(private_auth), encoding="utf-8")
    (source / "latest.json").write_text(
        json.dumps({"status": "ok", "authenticated_official": private_auth}),
        encoding="utf-8",
    )

    materialize(source, output, "fast_decision", "d" * 40)

    source_auth = json.loads((source / "auth.json").read_text())
    public_auth = json.loads((output / "data" / "auth.json").read_text())
    public_latest = json.loads((output / "data" / "latest.json").read_text())

    assert "safe_finance" in source_auth
    assert public_auth["public_projection"] == PUBLIC_AUTH_PROJECTION
    assert public_latest["authenticated_official"]["public_projection"] == PUBLIC_AUTH_PROJECTION
    for payload in (public_auth, public_latest["authenticated_official"]):
        assert "safe_finance" not in payload
        assert "draft_integrity" not in payload
        assert "chip_state" not in payload
        assert "transfers_latest" not in payload
        assert "endpoint_health" not in payload
        serialized = json.dumps(payload)
        assert "private-fingerprint" not in serialized
        assert "selling_price" not in serialized
        assert "purchase_price" not in serialized

    result = verify_publication(output / "data", source_commit="d" * 40, profile="fast_decision")
    assert result["status"] == "PASS"
    assert result["public_authenticated_projection_verified"] is True


def test_publication_verifier_rejects_private_state_embedded_in_latest(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _write_snapshot(
        data_dir,
        {
            "latest.json": {
                "authenticated_official": {
                    "public_projection": PUBLIC_AUTH_PROJECTION,
                    "state": "VALID",
                    "raw_authenticated_payload_persisted": False,
                    "draft_integrity": {"fingerprint": "private"},
                }
            }
        },
    )

    with pytest.raises(RuntimeError, match="non-public authenticated fields"):
        verify_publication(data_dir, source_commit="a" * 40, profile="fast_decision")


def test_publication_verifier_rejects_source_commit_mismatch(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _write_snapshot(data_dir, {"latest.json": {"status": "ok"}}, source_commit="b" * 40)

    with pytest.raises(RuntimeError, match="source_commit mismatch"):
        verify_publication(data_dir, source_commit="c" * 40, profile="fast_decision")
