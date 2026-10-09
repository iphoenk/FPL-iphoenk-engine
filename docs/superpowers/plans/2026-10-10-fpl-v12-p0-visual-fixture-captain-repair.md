# FPL V12 P0 Visual, Fixture & Captain Production Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make canonical DEEP output readable and mobile-first for S05/S06, and make the seven-layer captain decision consistently expose Bruno/Haaland as the computed provisional priorities when evidence supports that preference, without hardcoding or weakening existing production gates.

**Architecture:** Keep public code authoritative for canonical facts, decision payloads, and Markdown presentation. Enrich S05 from the Official FPL fixture identity plus the verified venue map, then bind weather by exact fixture ID and kickoff. Render S06 as a responsive self-contained pitch block using canonical XI/bench data, while preserving the existing semantic contract and S08/S19 state distinction. Validate rendered Markdown and generated visual HTML separately.

**Tech Stack:** Python 3, pytest, existing V12 orchestration/presentation locks, Markdown-compatible HTML/SVG for the pitch surface, existing GitHub Actions production workflows.

**Spec:** User request dated 2026-10-10: `FPL MASTER V12 — P0 VISUAL, FIXTURE & CAPTAIN PRODUCTION REPAIR`.

## Global Constraints

- Do not touch PR #809, P1.7, Monte Carlo 500K, full universe/routes, WatchlistScore weights, S16B lifecycle, or private security architecture.
- Fixture IDs remain internal references; user-facing S05 labels must be `Home Team vs Away Team` with honest venue and kickoff status.
- Weather is exact-fixture and exact-kickoff contextual enrichment only and cannot mutate xPts.
- S06 must be canonical-data driven, show all XI11 plus bench4, and preserve canonical versus provisional C/VC semantics.
- Preserve DEEP 22 sections and S16B lifecycle, PRICE 12 sections, and MATCH 13 sections.
- Do not fabricate unavailable correlations, goalkeeper calibration, rank simulations, receipts, or natural occurrences.

## Review Focus

- A fixture whose venue is not in the verified map must render `VENUE UNAVAILABLE`, not a guessed stadium.
- Two fixtures on the same date must not share weather merely because their dates match; exact fixture ID and kickoff must bind.
- A non-LOCK captain payload must never render a provisional recommendation as an executable current C/VC.
- A malformed or incomplete XI must fail soft and visibly report missing players instead of silently hardcoding names.
- A 375px viewport must preserve readable player names, no overlap, and no horizontal overflow.

### Task 1: S05 Fixture Identity and Weather Binding

**Files:**
- Modify: `src/engines/v12_s05_binding.py`
- Modify: `src/engines/v12_report_orchestration.py`
- Test: `tests/test_fixture_workload_weather_binding.py`
- Test: `tests/test_visible_rendered_contract.py`

**Interfaces:**
- Consumes Official FPL `bootstrap.teams` and planning fixtures.
- Produces `fixtures_display`, with `fixture_id`, `home_team`, `away_team`, `home_away`, `kickoff_wib`, `fixture_status`, `rest_days`, `venue`, `venue_status`, and exact weather binding metadata.

- [ ] Write failing tests for readable home/away labels, WIB conversion, verified venue fallback, and exact fixture/kickoff weather binding.
- [ ] Run the focused tests and observe the expected failure against the current numeric/raw S05 rendering.
- [ ] Implement the smallest enrichment/renderer change. Use the existing verified venue registry and preserve `VENUE UNAVAILABLE` on missing or mismatched home-team identity.
- [ ] Run focused S05 and visible-contract tests, then the full relevant regression subset.
- [ ] Commit `fix(v12): render readable fixture identity and exact weather binding`.

### Task 2: Canonical S06 Mobile Pitch Surface

**Files:**
- Modify: `src/engines/v12_report_orchestration.py`
- Create: `src/engines/v12_mobile_pitch.py`
- Test: `tests/test_visible_report_content_contract.py`
- Test: `tests/test_mobile_pitch_rendering.py`

**Interfaces:**
- Consumes canonical `starting_xi`, `bench`, `formation`, xPts, and captain state.
- Produces a self-contained responsive `s06_pitch_html` block and a semantic fallback line set. No player IDs, names, formation, or xPts are hardcoded.

- [ ] Write failing tests for XI11/bench4 completeness, formation order FWD→MID→DEF→GK, C/VC badge identity, and 375/390/430px overflow/clipping guards.
- [ ] Run the tests and observe failure because the current S06 renderer emits only text lines.
- [ ] Implement the pitch component with dark-green field markings, circular tokens, dark nameplates, responsive sizing, and a separate bench card. Keep it data driven and fail soft.
- [ ] Run focused visual-contract tests and render fixture snapshots at 375, 390, and 430 CSS pixels.
- [ ] Commit `feat(v12): add canonical mobile starting-xi pitch rendering`.

### Task 3: Seven-Layer Captain Semantic Consistency

**Files:**
- Modify: `src/engines/v12_captain_frontier.py`
- Modify: `src/engines/v12_report_orchestration.py`
- Modify: `src/engines/v12_deep_delivery.py`
- Test: `tests/test_captain_visible_provisional_baseline.py`
- Test: `tests/test_captain_report_contracts.py`

**Interfaces:**
- Consumes existing canonical frontier, PMF tails, start/security evidence, Competitive Window evidence, and shared-world status.
- Produces one canonical captain decision object consumed by S06/S08/S18/S19, including selected canonical C/VC, recommended priority C/VC, state, outstanding evidence, and deadline action.

- [ ] Write failing tests for the current GW6 evidence: Bruno/Haaland priority in PREPARE when attacker tail/security evidence outranks the marginal goalkeeper xPts lead, while preserving Tzolakis as model challenger and never claiming LOCK.
- [ ] Run the tests and observe the current Tzolakis/B.Fernandes baseline mismatch.
- [ ] Implement computed priority reconciliation only when the required evidence is present. Keep unavailable shared-world, goalkeeper calibration, or rank evidence explicitly unavailable and keep PREPARE.
- [ ] Render and validate S06/S08/S18/S19 semantic consistency, including canonical-versus-recommended labels.
- [ ] Commit `fix(v12): reconcile provisional captain priorities across report sections`.

### Task 4: Whole-Report Mobile Presentation and QA Gates

**Files:**
- Modify: `src/engines/v12_deep_presentation_lock.py`
- Modify: `src/runtime_v6/domains/report_plane/human_presentation_qa.py`
- Create: `tests/test_mobile_report_rendering.py`
- Modify: relevant presentation-contract tests.

- [ ] Write failing tests for S01–S19 mobile-readable content, no raw dictionaries, S11/S12/S13/S15B exact counts, S18 route table, and section order/count.
- [ ] Run the semantic and rendering tests, recording failures separately for canonical/Markdown QA and user-visible mobile UI QA.
- [ ] Implement only the presentation-layer changes needed to satisfy the approved mobile language without altering analytics authority.
- [ ] Run the full V12 verification subset and the actual render snapshots at all three mobile widths.
- [ ] Commit `test(v12): enforce mobile presentation and dual QA gates`.

### Task 5: Production Delivery and Evidence Verification

**Files:**
- Modify only necessary workflow/config files discovered during Tasks 1–4.
- No private report file is edited manually.

- [ ] Re-fetch current main, open PRs, required checks, scheduler configuration, issue #431 state, and private latest pointers.
- [ ] Push only the focused branch/PR if no existing PR covers the same changes; do not duplicate an existing PR or issue command.
- [ ] Run CI, merge only after required checks pass, and verify the deployed main SHA.
- [ ] Execute one authorized controlled production run if the existing workflow supports it, then verify prefetch, auth authority, V12, Stage3, MC500K, QA, publisher, receipt, and latest pointer.
- [ ] Inspect the exact private canonical report and generated mobile render. Verify any natural occurrence separately and never backdate it.
- [ ] Record controlled and natural run IDs separately, plus exact receipt/report links and remaining blockers.

