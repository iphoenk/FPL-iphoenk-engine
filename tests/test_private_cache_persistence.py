from __future__ import annotations

import base64
import json
from pathlib import Path

from src.engines import v12_lineup_optimizer as lineup
from src.engines import v12_monte_carlo as mc
from src.engines.private_cache_crypto import (
    SECURE_ENCRYPTED_PERSONAL_CACHE,
    SECURE_NO_PERSONAL_CACHE,
)


def _key(byte: int) -> bytes:
    return bytes([byte]) * 32


def _set_key(monkeypatch, byte: int) -> None:
    monkeypatch.setenv(
        "FPL_V12_PRIVATE_CACHE_KEY_B64",
        base64.b64encode(_key(byte)).decode("ascii"),
    )


def test_p17_secure_encrypted_profile_round_trips_without_plaintext(
    monkeypatch,
    tmp_path,
):
    root = tmp_path / "p17"
    monkeypatch.setenv(lineup.P17_DECISION_CACHE_ENV, str(root))
    monkeypatch.setenv(
        lineup.PRIVATE_CACHE_PROFILE_ENV,
        SECURE_ENCRYPTED_PERSONAL_CACHE,
    )
    _set_key(monkeypatch, 21)
    key = "a" * 64
    monkeypatch.setattr(lineup, "_decision_core_cache_key", lambda players: key)
    calls = {"n": 0}

    def build(players):
        calls["n"] += 1
        return {
            "legal_xi_count": 1,
            "private_marker": "CAPTAIN_PRIVATE_PLAYER",
        }

    monkeypatch.setattr(lineup, "_decision_core", build)

    first = lineup._decision_core_cached([{"element": 999}])
    second = lineup._decision_core_cached([{"element": 999}])
    assert first == second
    assert calls["n"] == 1

    files = list(root.rglob("*"))
    payload_files = [path for path in files if path.is_file()]
    assert len(payload_files) == 1
    assert payload_files[0].suffixes[-2:] == [".aead", ".json"]
    serialized = payload_files[0].read_text(encoding="utf-8")
    envelope = json.loads(serialized)
    assert set(envelope) == {
        "schema_version",
        "crypto_version",
        "nonce_b64",
        "ciphertext_b64",
        "tag_b64",
    }
    assert "CAPTAIN_PRIVATE_PLAYER" not in serialized
    assert "999" not in serialized
    assert key not in serialized
    assert not list(root.rglob("*.pkl"))


def test_p17_wrong_key_is_safe_miss_and_exact_recompute(
    monkeypatch,
    tmp_path,
):
    root = tmp_path / "p17"
    monkeypatch.setenv(lineup.P17_DECISION_CACHE_ENV, str(root))
    monkeypatch.setenv(
        lineup.PRIVATE_CACHE_PROFILE_ENV,
        SECURE_ENCRYPTED_PERSONAL_CACHE,
    )
    monkeypatch.setattr(
        lineup,
        "_decision_core_cache_key",
        lambda players: "b" * 64,
    )
    calls = {"n": 0}

    def build(players):
        calls["n"] += 1
        return {"legal_xi_count": 1, "generation": calls["n"]}

    monkeypatch.setattr(lineup, "_decision_core", build)
    _set_key(monkeypatch, 22)
    assert lineup._decision_core_cached([])["generation"] == 1
    _set_key(monkeypatch, 23)
    assert lineup._decision_core_cached([])["generation"] == 2
    assert not list(root.rglob("*.pkl"))


def test_p17_no_personal_cache_profile_never_persists(
    monkeypatch,
    tmp_path,
):
    root = tmp_path / "p17"
    monkeypatch.setenv(lineup.P17_DECISION_CACHE_ENV, str(root))
    monkeypatch.setenv(
        lineup.PRIVATE_CACHE_PROFILE_ENV,
        SECURE_NO_PERSONAL_CACHE,
    )
    monkeypatch.setattr(
        lineup,
        "_decision_core",
        lambda players: {"legal_xi_count": 1},
    )
    lineup._decision_core_cached([])
    assert not root.exists()


def test_mc_secure_encrypted_profile_round_trips_and_wrong_key_misses(
    monkeypatch,
    tmp_path,
):
    root = tmp_path / "mc"
    monkeypatch.setenv(mc.MC_SIM_CACHE_ENV, str(root))
    monkeypatch.setenv(
        mc.PRIVATE_CACHE_PROFILE_ENV,
        SECURE_ENCRYPTED_PERSONAL_CACHE,
    )
    key = "c" * 64
    summary = {
        "metrics": {"R1": {"1": {"private_route": "OUT_TO_IN"}}},
        "pairwise": {},
        "sampling": {},
        "convergence": {"status": "PASS"},
        "execution_state": "CANONICAL",
        "canonical_pass": True,
        "upside_threshold": 8.0,
    }
    _set_key(monkeypatch, 24)
    mc._save_mc_summary_cache(key, summary)
    assert mc._load_mc_summary_cache(key) == summary

    payload_files = [path for path in root.rglob("*") if path.is_file()]
    assert len(payload_files) == 1
    serialized = payload_files[0].read_text(encoding="utf-8")
    assert "OUT_TO_IN" not in serialized
    assert key not in serialized
    assert not list(root.rglob("*.pkl"))

    _set_key(monkeypatch, 25)
    assert mc._load_mc_summary_cache(key) is None


def test_mc_no_personal_cache_profile_never_persists(
    monkeypatch,
    tmp_path,
):
    root = tmp_path / "mc"
    monkeypatch.setenv(mc.MC_SIM_CACHE_ENV, str(root))
    monkeypatch.setenv(
        mc.PRIVATE_CACHE_PROFILE_ENV,
        SECURE_NO_PERSONAL_CACHE,
    )
    mc._save_mc_summary_cache("d" * 64, {"x": 1})
    assert not root.exists()
    assert mc._load_mc_summary_cache("d" * 64) is None


def test_production_workflow_never_uses_plaintext_personal_cache_or_pr_target():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "v12-integrated-report-runner.yml"
    ).read_text(encoding="utf-8")
    assert "pull_request_target" not in workflow
    assert "SECURE_ENCRYPTED_PERSONAL_CACHE" in workflow
    assert "SECURE_NO_PERSONAL_CACHE" in workflow
    assert "FPL_V12_PRIVATE_CACHE_KEY_B64" in workflow
    assert "branch acceptance unexpectedly received production decrypt key" in workflow
    assert "non-AEAD file found in restored production personal cache" in workflow
    assert "find .cache/v12-p17 .cache/v12-mc -type f ! -name '*.aead.json'" in workflow
    assert "actions/cache/restore@v4" in workflow
    assert "actions/cache/save@v4" in workflow
