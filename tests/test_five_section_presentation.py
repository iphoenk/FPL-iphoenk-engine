"""Mandatory five-section presentation contract: deterministic presentation QA, fail-closed pointer gate."""
from __future__ import annotations

import json

import pytest

from src.engines import v12_five_section_presentation as fs
from test_p0b_missed_slot_reconciliation import DEEP_SLOT, FakeReader, private_files, synthetic_deep_body
from test_verified_pointer import NOW
from ops import verified_pointer as vp

SLOT_TEXT = "25 Oct 2026, 12:30 WIB"
TITLES = ["OVERVIEW & ACTION", "OUR15 & XI", "ANALYTICS", "MINI-LEAGUE & COMPETITIVE", "FINAL DECISION & QA"]


def _body(**kw):
    return synthetic_deep_body(7, DEEP_SLOT, **kw).decode()


def _check(body, view=None, **kw):
    view = view if view is not None else fs.build_view(body)
    kw.setdefault("expected_gw", 7)
    kw.setdefault("expected_slot_wib", SLOT_TEXT)
    return fs.validate_view(view, canonical_body=body, **kw)


def test_config_is_an_exact_partition_of_the_canonical_sections():
    assert fs.config_failures() == []
    cfg = fs.load_config()
    assert cfg["top_level_sections"] == TITLES and list(cfg["section_groups"]) == TITLES


def test_valid_report_has_exactly_five_ordered_sections_and_passes():
    body = _body()
    view = fs.build_view(body)
    assert [l[3:] for l in view.splitlines() if l.startswith("## ")] == TITLES
    assert _check(body) == []


def test_every_canonical_section_appears_once_in_its_group_and_text_is_verbatim():
    body = _body()
    view = fs.build_view(body)
    cfg = fs.load_config()
    for title, ids in cfg["section_groups"].items():
        start = view.index(f"## {title}")
        end = view.find("\n## ", start + 1)
        chunk = view[start: end if end > 0 else len(view)]
        for sid in ids:
            if sid == "S16B":
                continue
            assert chunk.count(f"### {int(sid[1:3])}{sid[3:]}. ") == 1
    assert "Current C: Haaland; Current VC: Groß; state LOCK." in view
    assert "s06-dashboard" in view


def test_deterministic_same_input_same_output():
    body = _body()
    assert fs.build_view(body) == fs.build_view(body)


def test_nested_headings_are_demoted_never_new_top_level_sections():
    body = _body().replace("content 11", "#### INNER\ncontent 11").replace("content 12", "## EXTRA SECTION\nx")
    view = fs.build_view(body)
    assert view.count("\n## ") == 5 or [l for l in view.splitlines() if l.startswith("## ")] == ["## " + t for t in TITLES]


@pytest.mark.parametrize("mutation,code", [
    (lambda v: v.replace("## ANALYTICS", "## ANALYTICS\n\n## ANALYTICS 2"), "SECTION_COUNT=6"),
    (lambda v: v.replace("## ANALYTICS", "## TEMP").replace("## MINI-LEAGUE & COMPETITIVE", "## ANALYTICS").replace("## TEMP", "## MINI-LEAGUE & COMPETITIVE"),
     "SECTION_ORDER_OR_TITLE_MISMATCH"),
    (lambda v: v.replace("## FINAL DECISION & QA", "## FINAL DECISION"), "SECTION_ORDER_OR_TITLE_MISMATCH"),
    (lambda v: v.replace("### 11. SECTION 11", "### 11. RENAMED"), "VIEW_NOT_VERBATIM_REGROUPING_OF_CANONICAL_BODY"),
])
def test_view_structure_errors_fail_closed(mutation, code):
    body = _body()
    assert code in _check(body, mutation(fs.build_view(body)))


def test_missing_or_dropped_required_content_fails():
    body = _body()
    dropped = fs.build_view(body).replace("### 15B. SECTION 15B", "").replace("content 15B", "")
    assert "VIEW_NOT_VERBATIM_REGROUPING_OF_CANONICAL_BODY" in _check(body, dropped)
    no_s11 = body.replace("## 11. SECTION 11\nStatus: COMPLETE\ncontent 11\n", "")
    assert "CANONICAL_SECTION_MISSING=S11" in _check(no_s11)


def test_duplicate_canonical_section_and_unknown_section_fail():
    body = _body() + "\n## 8. CAPTAIN AGAIN\nx\n"
    assert "CANONICAL_SECTION_DUPLICATE=S08" in _check(body)
    assert "CANONICAL_SECTION_UNKNOWN=S25" in _check(_body() + "\n## 25. NOPE\nx\n")


def test_duplicate_xi_player_fails():
    xi = ["Verbruggen", "Calafiori", "Konsa", "De Cuyper", "Gvardiol", "Rogers", "Tavernier", "Groß", "Palmer",
          "Mbeumo", "Mbeumo"]
    failures = _check(_body(xi=xi, captain="Mbeumo", vice="Groß"))
    assert "XI_DUPLICATE_PLAYER" in failures


def test_xi_size_bench_size_and_overlap_fail():
    assert "XI_COUNT=10" in _check(_body(xi=["A", "B", "C", "D", "E", "F", "G", "Groß", "Haaland", "Z"]))
    assert "BENCH_INVALID=3" in _check(_body(bench=["Tzolakis", "Ajayi", "Barry"]))
    assert "XI_BENCH_OVERLAP" in _check(_body(bench=["Tzolakis", "Palmer", "Ajayi", "Barry"]))


def test_wrong_gameweek_fails():
    body = _body()
    assert "GW_MISMATCH=7!=8" in _check(body, expected_gw=8)
    assert "GW_MISSING" in _check(body.replace("Planning GW: GW7\n", ""))


def test_captain_vice_must_be_in_xi_distinct_and_consistent():
    assert "CV_NOT_IN_XI" in _check(_body(captain="Salah"))
    assert "CV_SAME_PLAYER" in _check(_body(vice="Haaland"))
    body = _body().replace("Captain: Haaland (LOCK)", "Captain: Palmer (LOCK)")
    assert "CV_INCONSISTENT_ACROSS_SECTIONS" in _check(body)
    assert "CV_MISSING_S08" in _check(_body().replace("Current C: Haaland; Current VC: Groß;", ""))


def test_inconsistent_xi_between_s06_and_s19_fails():
    body = _body()
    lines = body.splitlines()
    idx = next(i for i, l in enumerate(lines) if l.startswith("XI: formation"))
    lines[idx] = lines[idx].replace("Palmer", "Foden")
    assert "XI_INCONSISTENT_S06_S19" in _check("\n".join(lines))


def test_occurrence_slot_must_match_header():
    body = _body()
    assert "OCCURRENCE_SLOT_MISMATCH" in _check(body, expected_slot_wib="25 Oct 2026, 21:30 WIB")


def test_degraded_state_must_stay_explicit_and_pitch_must_survive():
    body = _body(status="READY_DEGRADED")
    assert _check(body) == []
    view = fs.build_view(body).replace("READY_DEGRADED", "READY")
    assert "DEGRADED_STATE_NOT_EXPLICIT" in _check(body, view) or "VIEW_NOT_VERBATIM_REGROUPING_OF_CANONICAL_BODY" in _check(body, view)
    assert "PITCH_DASHBOARD_DROPPED" in _check(body, fs.build_view(body).replace("s06-dashboard", "x"))


def test_explicit_degraded_fallback_has_five_sections_and_no_report_claims():
    out = fs.build_degraded_fallback("verified.json absent")
    assert out.startswith(fs.load_config()["degraded_marker"])
    assert [l[3:] for l in out.splitlines() if l.startswith("## ")] == TITLES
    assert fs.validate_view(out) == []
    assert "DEGRADED_FALLBACK_CONTAINS_REPORT_CLAIMS" in fs.validate_view(out + "\nXI: a, b\n")
    assert "SECTION_COUNT=4" in fs.validate_view(out.replace("## ANALYTICS\nNOT AVAILABLE: no verified canonical data. Nothing was inferred or reused.\n", ""))


def test_fallback_is_not_canonical_without_marker():
    unmarked = fs.build_degraded_fallback("x").replace(fs.load_config()["degraded_marker"], "STATUS")
    assert "CANONICAL_BODY_REQUIRED" in fs.validate_view(unmarked)


def test_parser_errors_fail_closed():
    assert fs.gate("", expected_gw=7, expected_slot_wib=SLOT_TEXT)  # non-empty failures


# ---- pointer gate -------------------------------------------------------------------------------

def _files(**kw):
    return private_files("DEEP", DEEP_SLOT, **kw)


def test_pointer_entry_records_contract_pass_for_a_conforming_deep():
    entry = vp.build_entry(FakeReader(_files()), "DEEP", DEEP_SLOT, now=NOW, orchestrator_run="1")
    assert entry["presentation_contract"] == "FIVE_SECTION_V1_PASS"


@pytest.mark.parametrize("bad", [
    synthetic_deep_body(7, DEEP_SLOT, captain="Salah"),
    synthetic_deep_body(8, DEEP_SLOT),
    synthetic_deep_body(7, "2026-10-25T21:30:00+07:00"),
    synthetic_deep_body(7, DEEP_SLOT, bench=["Tzolakis", "Ajayi", "Barry"]),
    b"# report\n",
], ids=["wrong_captain", "wrong_gw", "wrong_slot", "short_bench", "not_a_report"])
def test_nonconforming_deep_is_never_a_pointer_candidate(bad):
    with pytest.raises(vp.Unverified) as exc:
        vp.build_entry(FakeReader(_files(body=bad)), "DEEP", DEEP_SLOT, now=NOW, orchestrator_run="1")
    assert exc.value.reasons[0] == "PRESENTATION_CONTRACT_FAILED"


def test_failed_contract_leaves_the_pointer_unchanged():
    from test_verified_pointer import MemStore

    store = MemStore()
    good = vp.build_entry(FakeReader(_files()), "DEEP", DEEP_SLOT, now=NOW, orchestrator_run="1")
    vp.advance(store, good)
    before = dict(store.files)
    later = "2026-10-25T21:30:00+07:00"
    with pytest.raises(vp.Unverified):
        vp.build_entry(FakeReader(private_files("DEEP", later, body=synthetic_deep_body(7, later, vice="Haaland"))),
                       "DEEP", later, now=NOW, orchestrator_run="2")
    assert store.files == before and json.loads(before["latest/verified.json"][0])["modes"]["DEEP"]


def test_non_lock_provisional_pair_uses_baseline_wording_and_is_validated_not_skipped():
    """Regression: the renderer words a non-LOCK pair 'Current C baseline'; that is a valid report, not a defect."""
    body = _body(cv_state="PREPARE")
    assert "Current C baseline: Haaland; Current VC baseline: Groß; state PREPARE." in body
    assert _check(body) == []
    facts = fs.extract_facts(fs.parse_canonical(body))
    assert facts["cv"]["S08"] == ("Haaland", "Groß") and facts["cv_state"] == {"S08": "PREPARE", "S19": "PREPARE"}


def test_baseline_pair_is_still_checked_for_membership_distinctness_and_state():
    assert "CV_NOT_IN_XI" in _check(_body(cv_state="PREPARE", captain="Salah"))
    assert "CV_SAME_PLAYER" in _check(_body(cv_state="PREPARE", vice="Haaland"))
    body = _body(cv_state="PREPARE").replace("Captain baseline: Haaland (PREPARE)", "Captain baseline: Haaland (LOCK)")
    assert "CV_STATE_INCONSISTENT" in _check(body)
    assert "CV_MISSING_S08" in _check(_body(cv_state="PREPARE").replace("Current C baseline: Haaland;", ""))
