# Official FPL High-Integrity Selection Shadow (22 October 2026)

## Objective

Improve the *validity of inputs* to P(start), cameo, DNP and expected-minute
analysis using only finalized Official FPL player-fixture outcomes. This is
**not** a new probability model. The only owner is
`src/engines/v12_player_minutes.py` (`V12_PLAYER_MINUTES`).

The shadow adapter `src/engines/v12_verified_selection_shadow.py`
validates the source receipt and settled match selection, then calls the
existing `build_player_selection_evidence` and `estimate_player_minutes`.

## Admission contract

- Official FPL element ID and fixture ID are exact and positive.
- Player and fixture identity state is `EXACT` or governed `VERIFIED` /
  `VERIFIED_MANUAL`.
- An upstream **independently authenticated** original Git readback receipt
  for `official_fpl` supplies a 64-char artifact SHA256. The adapter checks
  the shape and row binding only; it does not independently authenticate Git.
- Fixture is finished; `official_status` is `FINAL` or `DNP`.
- Starter must be a real boolean, and minutes must be finite, plausible
  (0-130), nonnegative and internally consistent with status.
- Source and each row observation precede the evidence cutoff. Cutoff must
  precede target-GW Official deadline; previous-GW rows only.
- Repeated identical fixture rows count **once**. Contradictory outcomes for
  the same fixture invalidate the fixture completely.
- A minimum of three admitted settled fixtures is a *guard against treating
  a tiny sample as sufficient coverage*, not a claim of calibration.
- Official FPL 25/50/75 flags are never treated as P(start), availability,
  or expected-minutes multipliers; unverified X, media and pundit opinions
  have zero numerical weight.
- No second xMins owner or role/manager/rotation scoring is created.

## Output and safety

A validated sample returns `READY_SHADOW`, including existing V12
`p_start`, `p_regular_cameo`, `p_late_cameo`, `p_dnp`, and xMins.
Every result, including READY_SHADOW, has
`eligible_for_live_scoring=false` and `publication_authorized=false`.

Unverified receipt, insufficient settled rows, conflicting identities,
future/postdeadline observations, or untrusted formats fail closed and return
**no numeric probability**. Model confidence is distinct from source validity:
`calibration=NOT_VERIFIED` until genuinely prospective predeadline forecasts
are compared against future finalized official outcomes.

## How to use in controlled shadow diagnostics

```python
from src.engines.v12_verified_selection_shadow import evaluate_official_selection_shadow

result = evaluate_official_selection_shadow(
    player=official_fpl_player,     # verified id from bootstrap
    rows=official_fpl_match_rows,   # each row has settled fixture + source SHA
    receipt=v6_authenticated_original_git_receipt,
    target_gw=next_gw,
    evidence_cutoff_at=source_cutoff_iso,
    target_deadline_at=official_gw_deadline_iso,
)
```

There is **no production pipeline reader attached** by this PR. The upstream
bridge must prove matching Official FPL original Git objects and normalized
row schema; this cannot be established using a boolean alone. Do not use the
sample fixture tests as evidence of real live source completeness.

## Gates before any numerical production promotion

1. Authentic V6 original Git source readback + SHA and identity crosswalk.
2. Controlled readback of current same-occurrence source and prospectively
   frozen forecast, before Official deadline.
3. Adequate player/GW coverage, documented exclusions, stable stale/conflict
   handling and regression to the existing canonical baseline.
4. Walk-forward future-GW Brier/log-loss for P(start)/DNP, cameo and xMins MAE,
   with per-position noninferiority and no hindsight leakage.
5. Canonical ownership review, CI, controlled DEEP E2E and natural-run readback.
6. Separate approval before any change to decision/lineup/transfer scoring.
   Do not alter MC500K, chip logic, schedule or source gate as part of this PR.

## Design distinction

Official *match selection evidence* is factual history and can improve the
*inputs* to a statistical model. Historical inclusion and numerical Brier
calibration are separate claims. Until both are proven, probability output
is shadow-only and must not be described as high-confidence or GREEN.
