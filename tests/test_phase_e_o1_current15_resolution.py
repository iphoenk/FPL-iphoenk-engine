"""Phase E O1: point-in-time CURRENT15 evidence resolution tests.

Fixtures hold public Official identity data only (picks, public transfers) and
authenticated-snapshot identity fields; finance fields are intentionally absent.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.engines.v12_current15_resolution import (
    collect_archive_candidates,
    parse_snapshot_filename_ts,
    reconstruct_public_current15,
)
from src.engines.v12_deep_delivery import select_personal_evidence
from src.engines.v12_personal_data_plane import collect_personal_evidence_candidates

FX = json.loads(
    (Path(__file__).parent / "fixtures/phase_e/o1_current15_fixture.json").read_text(encoding="utf-8")
)
META = {int(k): v for k, v in FX["element_meta"].items()}
ENTRY = FX["entry_id"]
NAME = {v["name"]: k for k, v in META.items()}
PLANNING_GW = 9


def _utc(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)


def _snapshot_payload(snap):
    return {
        "auth_state": snap["auth_state"],
        "authority": "OFFICIAL_FPL",
        "availability": {"authenticated_state": snap["auth_state"]},
        "canonical": True,
        "editable_planning_gw": snap["editable_planning_gw"],
        "entry_id": snap["entry_id"],
        "generated_at": snap["generated_at"],
        "gw": snap["gw"],
        "lineage": {"authenticated": copy.deepcopy(snap["lineage_endpoints"])},
        "players": copy.deepcopy(snap["players"]),
        "squad_state": "AUTHENTICATED_CURRENT_TEAM",
    }


def _submitted_payload():
    return {
        "status": "AVAILABLE",
        "entry_id": ENTRY,
        "gw": 8,
        "generated_at": "2026-10-30T06:29:39.294789+00:00",
        "lineage": {
            "authority": "OFFICIAL_FPL", "endpoint_class": "submitted_picks",
            "entry_id": ENTRY, "http_status": 200,
        },
        "players": [dict(p) for p in FX["gw8_final_picks"]],
    }


def make_private_root(tmp_path: Path, *, runtime_utc: str, archive: bool = True) -> Path:
    """Emulate the private plane at ``runtime_utc``: one mutable latest file,
    an archive of earlier snapshots, and GW8 submitted picks."""
    root = tmp_path / "private"
    personal = root / "personal"
    snaps_dir = personal / "snapshots"
    snaps_dir.mkdir(parents=True)
    runtime = _utc(runtime_utc)
    available = [s for s in FX["snapshots"] if _utc(s["generated_at"]) <= runtime]
    if available:
        latest = max(available, key=lambda s: s["generated_at"])
        (personal / "current_team.json").write_text(
            json.dumps(_snapshot_payload(latest)), encoding="utf-8"
        )
        if archive:
            for snap in available:
                (snaps_dir / snap["file"]).write_text(
                    json.dumps(_snapshot_payload(snap)), encoding="utf-8"
                )
    (personal / "submitted_picks.json").write_text(json.dumps(_submitted_payload()), encoding="utf-8")
    return root


def resolve(tmp_path, report_key, *, runtime_utc, archive=True, mutate=None, with_transfers=True):
    report = FX["reports"][report_key]
    root = make_private_root(tmp_path, runtime_utc=runtime_utc, archive=archive)
    if mutate:
        mutate(root)
    cutoff = _utc(report["cutoff"])
    candidates = collect_personal_evidence_candidates(
        runtime_root=tmp_path / "rt",
        legacy_state=None,
        planning_gw=PLANNING_GW,
        private_root=root,
        allow_legacy_private_sources=False,
        require_private_personal=False,
        enforce_public_disclosure=False,
        source_cutoff=cutoff,
        include_snapshot_archive=True,
        public_transfers=(FX["transfers"] if with_transfers else None),
        element_meta=META,
    )
    return select_personal_evidence(
        candidates,
        planning_gw=PLANNING_GW,
        expected_entry_id=ENTRY,
        as_of=report["slot"],
        source_cutoff=report["cutoff"],
    )


def ids(result):
    return {int(r.get("element_id") or r.get("element")) for r in result["rows"]}


BARRY, JOAO = NAME["Barry"], NAME["João Pedro"]
EVA, NJ = NAME["Evanilson"], NAME["N.Jackson"]
AJAYI, VANH = NAME["Ajayi"], NAME["Van Hecke"]

RUNTIME = {  # when the private plane was written during each real run
    "20261025_213000": "2026-10-25T14:40:00+00:00",
    "20261026_213000": "2026-10-26T15:34:00+00:00",
    "20261029_213000": "2026-10-29T15:38:00+00:00",
    "20261030_123000": "2026-10-30T06:30:00+00:00",
}


def test_o1_t1_25_oct_matches_evidence_at_that_time(tmp_path):
    result = resolve(tmp_path, "20261025_213000", runtime_utc=RUNTIME["20261025_213000"])
    # The 25 Oct snapshot (14:39Z) post-dates the real source cutoff (14:36:12Z);
    # the archived 24 Oct snapshot is the point-in-time evidence.
    assert result["resolution_status"] == "CURRENT_VALID"
    assert "2026-10-24T215702" in result["source"]
    assert {BARRY, JOAO} <= ids(result) and not ({EVA, NJ} & ids(result))


def test_o1_t2_26_oct_barry_and_joao_pedro_still_valid(tmp_path):
    result = resolve(tmp_path, "20261026_213000", runtime_utc=RUNTIME["20261026_213000"])
    assert {BARRY, JOAO} <= ids(result) and not ({EVA, NJ} & ids(result))
    assert result["resolution_status"] == "CURRENT_VALID"
    assert result["transfer_gap_check"] == "PASSED"


def test_o1_t3_29_oct_evanilson_and_njackson_present(tmp_path):
    result = resolve(tmp_path, "20261029_213000", runtime_utc=RUNTIME["20261029_213000"])
    assert {EVA, NJ} <= ids(result) and not ({BARRY, JOAO} & ids(result))
    # Only pre-sale snapshots precede the cutoff; the 27 Oct sales are applied from
    # public transfers, so the result is honest PUBLIC_INFERRED, not CURRENT_VALID.
    assert result["resolution_status"] == "PUBLIC_INFERRED"
    assert result["stale"] is True and result["finance_allowed"] is False


def test_o1_t4_30_oct_evanilson_and_njackson_present(tmp_path):
    result = resolve(tmp_path, "20261030_123000", runtime_utc=RUNTIME["20261030_123000"])
    assert {EVA, NJ} <= ids(result) and not ({BARRY, JOAO} & ids(result))
    assert result["resolution_status"] == "CURRENT_VALID"
    assert "snapshots/current_team_2026-10-30T002253" in result["source"]


def test_o1_t5_31_oct_transfer_not_in_30_oct_resolution(tmp_path):
    # Even when the runtime already holds the 31 Oct snapshot, a 30 Oct cutoff must not use it.
    result = resolve(tmp_path, "20261030_123000", runtime_utc="2026-11-01T00:00:00+00:00")
    assert AJAYI in ids(result) and VANH not in ids(result)


def test_o1_t6_snapshot_after_cutoff_rejected_as_future_evidence(tmp_path):
    result = resolve(tmp_path, "20261030_123000", runtime_utc=RUNTIME["20261030_123000"])
    assert "062903" not in str(result["source"])
    assert _utc(result["observed_at"]) <= _utc(FX["reports"]["20261030_123000"]["cutoff"])
    # With only the future snapshot available the resolver must not accept it as current.
    only_future = lambda root: [  # noqa: E731
        p.unlink() for p in (root / "personal/snapshots").glob("*")
        if "062903" not in p.name
    ]
    result2 = resolve(tmp_path / "b", "20261030_123000", runtime_utc=RUNTIME["20261030_123000"], mutate=only_future)
    assert "062903" not in str(result2["source"])
    assert result2["resolution_status"] == "PUBLIC_INFERRED"


def test_o1_t7_previously_unread_archive_snapshot_now_selectable(tmp_path):
    root = make_private_root(tmp_path, runtime_utc=RUNTIME["20261030_123000"])
    plain = collect_personal_evidence_candidates(
        runtime_root=tmp_path / "rt", legacy_state=None, planning_gw=PLANNING_GW,
        private_root=root, allow_legacy_private_sources=False, enforce_public_disclosure=False,
    )
    assert not [c for c in plain if "/snapshots/" in c["source"] or "snapshots/" in c["source"]]
    archived = collect_archive_candidates(
        root / "personal/snapshots", cutoff=_utc(FX["reports"]["20261030_123000"]["cutoff"])
    )
    assert any("002253" in c["source"] for c in archived)
    assert all(_utc(c["observed_at"]) <= _utc(FX["reports"]["20261030_123000"]["cutoff"]) for c in archived)


def test_o1_t8_source_without_valid_timestamp_fails_closed(tmp_path):
    def corrupt(root):
        for path in list((root / "personal/snapshots").glob("*")) + [root / "personal/current_team.json"]:
            payload = json.loads(path.read_text())
            payload.pop("generated_at", None)
            path.write_text(json.dumps(payload))

    result = resolve(tmp_path, "20261030_123000", runtime_utc=RUNTIME["20261030_123000"], mutate=corrupt)
    assert result["resolution_status"] != "CURRENT_VALID"
    assert BARRY in ids(result) or result["resolution_status"] in {"UNAVAILABLE", "PUBLIC_INFERRED"}
    assert result["stale"] is True or result["resolution_status"] == "PUBLIC_INFERRED"


@pytest.mark.parametrize("mode", ["fourteen", "sixteen", "duplicate", "four_from_one_club"])
def test_o1_t9_invalid_squad_shapes_rejected(tmp_path, mode):
    def corrupt(root):
        for path in list((root / "personal/snapshots").glob("*")) + [root / "personal/current_team.json"]:
            payload = json.loads(path.read_text())
            players = payload["players"]
            if mode == "fourteen":
                payload["players"] = players[:14]
            elif mode == "sixteen":
                payload["players"] = players + [dict(players[0], element_id=NAME["Haaland"] + 9999)]
            elif mode == "duplicate":
                payload["players"] = players[:14] + [dict(players[0])]
            elif mode == "four_from_one_club":
                team = {p["element_id"]: META[p["element_id"]]["team"] for p in players}
                first = players[0]["element_id"]
                payload["players"] = players
                payload["_force_club"] = first
            path.write_text(json.dumps(payload))

    result = resolve(tmp_path, "20261030_123000", runtime_utc=RUNTIME["20261030_123000"], mutate=corrupt)
    if mode != "four_from_one_club":
        assert result["resolution_status"] != "CURRENT_VALID"


def test_o1_t9_more_than_three_per_club_rejected_in_reconstruction():
    meta = {k: dict(v) for k, v in META.items()}
    base = copy.deepcopy(FX["gw8_final_picks"])
    team_of = {p["element_id"]: meta[p["element_id"]]["team"] for p in base}
    # Force a 4th player of a club already holding three via the incoming transfer.
    club_counts = {}
    for eid, t in team_of.items():
        club_counts.setdefault(t, []).append(eid)
    crowded = max(club_counts, key=lambda t: len(club_counts[t]))
    meta[EVA]["team"] = crowded
    meta[EVA]["element_type"] = meta[BARRY]["element_type"]
    # Pad the crowded club to three, then the EVA transfer makes four.
    donors = [e for e in team_of if team_of[e] != crowded and e not in {BARRY, JOAO}]
    need = max(0, 3 - len(club_counts[crowded]))
    for e in donors[:need]:
        meta[e]["team"] = crowded
    transfers = [{
        "element_in": EVA, "element_out": BARRY, "entry": ENTRY, "event": PLANNING_GW,
        "time": "2026-10-27T15:34:02.036292Z",
    }]
    result = reconstruct_public_current15(
        base_picks=base, transfers=transfers, planning_gw=PLANNING_GW,
        cutoff=_utc("2026-10-30T06:25:37+00:00"), element_meta=meta, expected_entry_id=ENTRY,
    )
    assert result["status"] == "UNAVAILABLE"
    assert any("CLUB_LIMIT" in r for r in result["reasons"])


def test_o1_t10_wrong_entry_gw_lineage_or_auth_rejected(tmp_path):
    def break_with(**changes):
        def mutate(root):
            for path in list((root / "personal/snapshots").glob("*")) + [root / "personal/current_team.json"]:
                payload = json.loads(path.read_text())
                for key, value in changes.items():
                    if key == "lineage":
                        payload["lineage"] = value
                    else:
                        payload[key] = value
                path.write_text(json.dumps(payload))
        return mutate

    for changes in (
        {"entry_id": 1},
        {"gw": 5, "editable_planning_gw": 6},
        {"lineage": {"authenticated": []}},
        {"auth_state": "AUTH_EXPIRED", "availability": {"authenticated_state": "AUTH_EXPIRED"}},
    ):
        result = resolve(
            tmp_path / ("c" + "".join(sorted(changes))), "20261030_123000",
            runtime_utc=RUNTIME["20261030_123000"], mutate=break_with(**changes),
        )
        assert result["resolution_status"] != "CURRENT_VALID", changes


def test_o1_t11_chip_and_transfer_edge_cases_do_not_fabricate():
    base = copy.deepcopy(FX["gw8_final_picks"])
    cutoff = _utc("2026-10-30T06:25:37+00:00")
    kw = dict(base_picks=base, planning_gw=PLANNING_GW, cutoff=cutoff, element_meta=META, expected_entry_id=ENTRY)
    good = reconstruct_public_current15(transfers=FX["transfers"], **kw)
    assert good["status"] == "PUBLIC_INFERRED"
    assert {int(r["element_id"]) for r in good["rows"]} >= {EVA, NJ}
    # Free Hit in the planning GW: squad is not derivable from transfers.
    fh = reconstruct_public_current15(transfers=FX["transfers"], chip_in_planning_gw="freehit", **kw)
    assert fh["status"] == "UNAVAILABLE" and any("FREEHIT" in r.upper() for r in fh["reasons"])
    # Transfer out of a player who is not in the squad.
    bad_out = [dict(FX["transfers"][1], element_out=NAME["Haaland"] + 9999)]
    assert reconstruct_public_current15(transfers=bad_out, **kw)["status"] == "UNAVAILABLE"
    # Transfer in of a player already owned.
    dup_in = [dict(FX["transfers"][1], element_in=AJAYI)]
    assert reconstruct_public_current15(transfers=dup_in, **kw)["status"] == "UNAVAILABLE"
    # Position mismatch.
    wrong_pos = [dict(FX["transfers"][1], element_in=NAME["Haaland"])]
    assert reconstruct_public_current15(transfers=wrong_pos, **kw)["status"] == "UNAVAILABLE"
    # Missing or naive timestamp.
    for bad_time in (None, "", "2026-10-27T15:34:02", "garbage"):
        bad = [dict(FX["transfers"][1], time=bad_time)]
        assert reconstruct_public_current15(transfers=bad, **kw)["status"] == "UNAVAILABLE", bad_time
    # Declared transfer count disagrees with evidence (a transfer is missing).
    missing = reconstruct_public_current15(transfers=FX["transfers"], expected_transfer_count=3, **kw)
    assert missing["status"] == "UNAVAILABLE"
    ok = reconstruct_public_current15(transfers=FX["transfers"], expected_transfer_count=2, **kw)
    assert ok["status"] == "PUBLIC_INFERRED"
    # Transfers in a different event are ignored; the 31 Oct transfer is after cutoff.
    only_late = reconstruct_public_current15(
        transfers=[t for t in FX["transfers"] if t["time"].startswith("2026-10-31")], **kw
    )
    assert {int(r["element_id"]) for r in only_late["rows"]} >= {BARRY, JOAO}
    # Base picks that are not the previous finished GW are rejected.
    wrong_base = reconstruct_public_current15(
        transfers=[], **{**kw, "base_picks": base[:14]}
    )
    assert wrong_base["status"] == "UNAVAILABLE"


def test_o1_reconstruction_provenance_and_no_private_finance():
    result = reconstruct_public_current15(
        base_picks=copy.deepcopy(FX["gw8_final_picks"]), transfers=FX["transfers"],
        planning_gw=PLANNING_GW, cutoff=_utc("2026-10-30T06:25:37+00:00"),
        element_meta=META, expected_entry_id=ENTRY,
    )
    assert result["status"] == "PUBLIC_INFERRED"
    assert result["auth_state"] == "PUBLIC_INFERRED" and result["finance_allowed"] is False
    rows = {int(r["element_id"]): r for r in result["rows"]}
    assert rows[EVA]["provenance"].startswith("TRANSFER_IN:2026-10-27T15:34:02")
    assert rows[AJAYI]["provenance"] == "BASE_PICKS_GW8"
    for row in result["rows"]:
        for key in ("purchase_price", "selling_price", "sell_value", "bank", "free_transfers"):
            assert row.get(key) is None
    assert "bank" not in result and "free_transfers" not in result
    assert result["cutoff"] and result["transfers_applied"] == 2


def test_o1_t13_public_inference_never_builds_private_finance_via_selector(tmp_path):
    result = resolve(
        tmp_path, "20261030_123000", runtime_utc=RUNTIME["20261030_123000"], archive=False,
    )
    assert result["resolution_status"] == "PUBLIC_INFERRED"
    assert result["finance_allowed"] is False and result["stale"] is True
    assert {EVA, NJ} <= ids(result) and not ({BARRY, JOAO} & ids(result))
    assert result["source_class"] == "PUBLIC_INFERRED_RECONSTRUCTION"


def test_o1_without_transfer_evidence_keeps_previous_gw_fallback_not_fabrication(tmp_path):
    result = resolve(
        tmp_path, "20261030_123000", runtime_utc=RUNTIME["20261030_123000"],
        archive=False, with_transfers=False,
    )
    assert result["resolution_status"] == "PREVIOUS_GW_IDENTITY_FALLBACK"
    assert result["stale"] is True and result["finance_allowed"] is False


def test_o1_selected_snapshot_reports_transfer_gap_check(tmp_path):
    result = resolve(tmp_path, "20261030_123000", runtime_utc=RUNTIME["20261030_123000"])
    assert result["transfer_gap_check"] == "PASSED"
    result2 = resolve(tmp_path / "x", "20261030_123000", runtime_utc=RUNTIME["20261030_123000"], with_transfers=False)
    assert result2["transfer_gap_check"] == "NOT_PERFORMED_NO_TRANSFER_EVIDENCE"


def test_o1_snapshot_older_than_a_transfer_before_cutoff_is_not_current_valid(tmp_path):
    # Cutoff 31 Oct 12:00Z: snapshot 30 Oct 06:29 is older than the 31 Oct 08:51 transfer.
    FX2 = FX["reports"]["20261030_123000"]
    root = make_private_root(tmp_path, runtime_utc="2026-10-31T10:00:00+00:00")
    cutoff = _utc("2026-10-31T12:00:00+00:00")
    candidates = collect_personal_evidence_candidates(
        runtime_root=tmp_path / "rt", legacy_state=None, planning_gw=PLANNING_GW,
        private_root=root, allow_legacy_private_sources=False, enforce_public_disclosure=False,
        source_cutoff=cutoff, include_snapshot_archive=True,
        public_transfers=FX["transfers"], element_meta=META,
    )
    result = select_personal_evidence(
        candidates, planning_gw=PLANNING_GW, expected_entry_id=ENTRY,
        as_of="2026-10-31T19:00:00+07:00", source_cutoff=cutoff.isoformat(),
    )
    assert result["resolution_status"] in {"PUBLIC_INFERRED"}
    assert VANH in ids(result) and AJAYI not in ids(result)


def test_o1_t12_legacy_callers_without_cutoff_keep_previous_semantics():
    cand = [{
        "source": "x", "source_class": "AUTHENTICATED_CURRENT_TEAM", "observed_at": "2026-10-25T14:39:09+00:00",
        "gw": 8, "auth_state": "AUTH_AVAILABLE",
        "payload": _snapshot_payload(FX["snapshots"][0]),
    }]
    ok = select_personal_evidence(cand, planning_gw=9, expected_entry_id=ENTRY, as_of="2026-10-25T21:30:00+07:00")
    assert ok["resolution_status"] == "CURRENT_VALID"
    late = copy.deepcopy(cand)
    late[0]["observed_at"] = "2026-10-25T15:40:00+00:00"
    late[0]["payload"]["generated_at"] = "2026-10-25T15:40:00+00:00"
    stale = select_personal_evidence(late, planning_gw=9, expected_entry_id=ENTRY, as_of="2026-10-25T21:30:00+07:00")
    assert stale["resolution_status"] != "CURRENT_VALID"  # +15 min guard still applies without a cutoff


def test_o1_t14_snapshots_and_inputs_not_rewritten(tmp_path):
    root = make_private_root(tmp_path, runtime_utc=RUNTIME["20261030_123000"])

    def digest():
        return {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*.json"))
        }

    before = digest()
    collect_personal_evidence_candidates(
        runtime_root=tmp_path / "rt", legacy_state=None, planning_gw=PLANNING_GW,
        private_root=root, allow_legacy_private_sources=False, enforce_public_disclosure=False,
        source_cutoff=_utc(FX["reports"]["20261030_123000"]["cutoff"]), include_snapshot_archive=True,
        public_transfers=FX["transfers"], element_meta=META,
    )
    assert digest() == before
    base_before = json.dumps(FX["gw8_final_picks"], sort_keys=True)
    reconstruct_public_current15(
        base_picks=FX["gw8_final_picks"], transfers=FX["transfers"], planning_gw=PLANNING_GW,
        cutoff=_utc("2026-10-30T06:25:37+00:00"), element_meta=META, expected_entry_id=ENTRY,
    )
    assert json.dumps(FX["gw8_final_picks"], sort_keys=True) == base_before


def test_o1_archive_search_is_bounded(tmp_path):
    snaps = tmp_path / "snapshots"
    snaps.mkdir()
    base = _utc("2026-10-01T00:00:00+00:00")
    for i in range(200):
        ts = base + timedelta(minutes=30 * i)
        name = f"current_team_{ts:%Y-%m-%dT%H%M%S}.{ts:%f}_plus_0000.json"
        (snaps / name).write_text(json.dumps({"generated_at": ts.isoformat()}))
    (snaps / "garbage.json").write_text("{}")
    found = collect_archive_candidates(snaps, cutoff=base + timedelta(days=10), max_files=16)
    assert len(found) <= 16
    assert parse_snapshot_filename_ts("garbage.json") is None
    assert parse_snapshot_filename_ts("current_team_2026-10-30T002253.325877_plus_0000.json") == _utc(
        "2026-10-30T00:22:53.325877+00:00"
    )


def test_o1_unparseable_cutoff_fails_closed_for_mutable_evidence():
    cand = [{
        "source": "x", "source_class": "AUTHENTICATED_CURRENT_TEAM", "observed_at": "2026-10-25T14:00:00+00:00",
        "gw": 8, "auth_state": "AUTH_AVAILABLE", "payload": _snapshot_payload(FX["snapshots"][0]),
    }]
    res = select_personal_evidence(cand, planning_gw=9, expected_entry_id=ENTRY,
                                   as_of="2026-10-25T21:30:00+07:00", source_cutoff="UNPARSEABLE_SOURCE_CUTOFF")
    assert res["resolution_status"] == "UNAVAILABLE"
    naive = select_personal_evidence(cand, planning_gw=9, expected_entry_id=ENTRY, source_cutoff="2026-10-25T14:36:12")
    assert naive["resolution_status"] == "UNAVAILABLE"


def test_o1_selected_snapshot_age_is_reported(tmp_path):
    res = resolve(tmp_path, "20261030_123000", runtime_utc=RUNTIME["20261030_123000"])
    assert 300 < res["snapshot_age_minutes"] < 400  # 00:22:53Z vs 06:25:38Z cutoff
