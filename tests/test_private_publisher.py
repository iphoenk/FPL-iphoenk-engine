from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from src.engines.v12_private_publisher import (
    PrivatePublishError,
    build_private_digest,
    publish_private_output,
)


def _write_fixture(root: Path) -> dict:
    section_ids = [
        "S01", "S02", "S03", "S04", "S05", "S06", "S06B",
        "S07", "S08", "S09", "S10", "S11", "S12", "S13",
        "S14", "S14B", "S15", "S15B", "S16", "S16B",
        "S17", "S18", "S19",
    ]
    bundle = {
        "report_mode": "DEEP",
        "report_slot": "2026-09-26T12:30:00+07:00",
        "planning_gw": 6,
        "runner_status": "PASS",
        "section_manifest": [{"id": value} for value in section_ids],
        "pre_render_qa": {"status": "PASS"},
        "post_render_qa": {"status": "PASS"},
        "human_facing_qa": {"status": "PASS"},
        "execution_proof": {"stage3_action": "WAIT"},
        "report": {"S03": {"delta": "IDENTITY_FIXTURE"}},
    }
    proof = {
        "runner_status": "PASS",
        "stage3_action": "WAIT",
        "rendered_section_ids": section_ids,
    }
    stage3 = {"status": "PASS", "stage3_action": "WAIT"}
    body = "# Synthetic canonical report\n\nDecision fixture is private.\n"
    (root / "report_bundle.json").write_text(
        json.dumps(bundle, indent=2), encoding="utf-8"
    )
    (root / "report_body.md").write_text(body, encoding="utf-8")
    (root / "execution_proof.json").write_text(
        json.dumps(proof, indent=2), encoding="utf-8"
    )
    (root / "stage3_acceptance.json").write_text(
        json.dumps(stage3, indent=2), encoding="utf-8"
    )
    return bundle


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_private_digest_is_deterministic_copy_of_canonical_status():
    bundle = {
        "report_mode": "DEEP",
        "report_slot": "x",
        "planning_gw": 6,
        "runner_status": "PASS",
        "section_manifest": [{"id": "S01"}, {"id": "S19"}],
        "pre_render_qa": {"status": "PASS"},
        "post_render_qa": {"status": "PASS"},
        "human_facing_qa": {"status": "PASS"},
    }
    proof = {"stage3_action": "WAIT"}
    first = build_private_digest(
        bundle, proof,
        canonical_bundle_sha256="a" * 64,
        canonical_body_sha256="b" * 64,
    )
    second = build_private_digest(
        copy.deepcopy(bundle), copy.deepcopy(proof),
        canonical_bundle_sha256="a" * 64,
        canonical_body_sha256="b" * 64,
    )
    assert first == second
    assert first["stage3_action"] == proof["stage3_action"]
    assert first["math_recomputed"] is False


def test_private_publisher_copies_canonical_files_bit_identical_and_preserves_ids(tmp_path):
    canonical = tmp_path / "canonical"
    private = tmp_path / "private"
    canonical.mkdir()
    bundle = _write_fixture(canonical)
    before = {name: _hash(canonical / name) for name in (
        "report_bundle.json", "report_body.md",
        "execution_proof.json", "stage3_acceptance.json"
    )}

    receipt = publish_private_output(
        canonical_dir=canonical,
        private_root=private,
        run_id="synthetic-1",
        season="2026-27",
        model_sha="a" * 40,
        runtime_sha="b" * 40,
    )

    destination = private / receipt["destination"]
    for name, digest in before.items():
        assert _hash(destination / name) == digest
        assert _hash(canonical / name) == digest

    copied_bundle = json.loads(
        (destination / "report_bundle.json").read_text(encoding="utf-8")
    )
    assert copied_bundle["section_manifest"] == bundle["section_manifest"]
    assert copied_bundle["report"]["S03"] == bundle["report"]["S03"]


def test_private_publish_is_idempotent_for_identical_occurrence(tmp_path):
    canonical = tmp_path / "canonical"
    private = tmp_path / "private"
    canonical.mkdir()
    _write_fixture(canonical)
    kwargs = dict(
        canonical_dir=canonical,
        private_root=private,
        run_id="synthetic-1",
        season="2026-27",
        model_sha="a" * 40,
        runtime_sha="b" * 40,
    )
    first = publish_private_output(**kwargs)
    second = publish_private_output(**kwargs)
    assert first == second


def test_private_publish_collision_fails_closed(tmp_path):
    canonical = tmp_path / "canonical"
    private = tmp_path / "private"
    canonical.mkdir()
    _write_fixture(canonical)
    receipt = publish_private_output(
        canonical_dir=canonical,
        private_root=private,
        run_id="synthetic-1",
        season="2026-27",
        model_sha="a" * 40,
        runtime_sha="b" * 40,
    )
    destination = private / receipt["destination"]
    (destination / "report_body.md").write_text("tampered", encoding="utf-8")
    with pytest.raises(PrivatePublishError):
        publish_private_output(
            canonical_dir=canonical,
            private_root=private,
            run_id="synthetic-1",
            season="2026-27",
            model_sha="a" * 40,
            runtime_sha="b" * 40,
        )


def test_private_publish_failure_never_creates_public_fallback(tmp_path):
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    _write_fixture(canonical)
    (canonical / "stage3_acceptance.json").write_text(
        json.dumps({"status": "FAIL"}), encoding="utf-8"
    )
    public = tmp_path / "public"
    with pytest.raises(PrivatePublishError):
        publish_private_output(
            canonical_dir=canonical,
            private_root=tmp_path / "private",
            run_id="synthetic-fail",
            season="2026-27",
            model_sha="a" * 40,
            runtime_sha="b" * 40,
        )
    assert not public.exists()


def test_latest_pointer_advances_across_distinct_occurrences_without_mutating_history(tmp_path):
    canonical = tmp_path / "canonical"
    private = tmp_path / "private"
    canonical.mkdir()
    _write_fixture(canonical)

    first = publish_private_output(
        canonical_dir=canonical,
        private_root=private,
        run_id="synthetic-1",
        season="2026-27",
        model_sha="a" * 40,
        runtime_sha="b" * 40,
    )
    first_dir = private / first["destination"]
    first_body_hash = _hash(first_dir / "report_body.md")

    bundle_path = canonical / "report_bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["report_slot"] = "2026-09-26T21:30:00+07:00"
    bundle_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    (canonical / "report_body.md").write_text(
        "# Synthetic canonical report\n\nSecond occurrence.\n",
        encoding="utf-8",
    )

    second = publish_private_output(
        canonical_dir=canonical,
        private_root=private,
        run_id="synthetic-2",
        season="2026-27",
        model_sha="a" * 40,
        runtime_sha="b" * 40,
    )

    latest = json.loads(
        (private / "latest/deep.json").read_text(encoding="utf-8")
    )
    assert latest["report_slot"] == "2026-09-26T21:30:00+07:00"
    assert first["destination"] != second["destination"]
    assert _hash(first_dir / "report_body.md") == first_body_hash
