# V12 S02 / CURRENT15 closure evidence — 2026-09-25

## Scope

Stage A root-cause closure and Stage B regression lock for S02 only.

Base production main:

`f1402818519237d3628184e298bd58c0240983bb`

Primary regression occurrence:

- run `35979672473`
- report slot `2026-09-24T14:20:00+07:00`
- model SHA `31b3e45c5089e9ea1ea2be10de3793b91df99a32`
- runtime-data-v6 SHA `9fc2ce5e590518c399765e6fd576bb96db6e5897`

No P1.7 optimizer, batch, package-utility hot path, MC parallelism, pruning, timeout, or V6 factual-plane code is changed by this branch.

## Stage A finding

The failure is **MIXED: ACQUISITION + RECONCILIATION**.

It is not a wall-clock freshness bug and it is not an acceptance-contract loophole.

At the failing occurrence:

1. `data/v6/personal/submitted_picks.json` was a fresh Official FPL public artifact with 15/15 picks, but it was bound to official current GW5.
2. V12 was planning GW6.
3. `data/v6/personal/current_team.json` was also GW5, `AUTH_EXPIRED`, and `SUBMITTED_PICKS_ONLY`; its private `me` lineage returned HTTP 401.
4. The model state at SHA `31b3e45c...` contained an older migrated 15-player identity with M.Sangaré and did not carry `explicit_user_confirmation`, an evidence timestamp, or an applicable planning GW. It therefore correctly was not accepted as planning-GW-current evidence.
5. `select_personal_evidence` consequently selected Official submitted GW5 picks as `PREVIOUS_GW_IDENTITY_FALLBACK`, `stale=true`, finance disallowed.
6. S02 correctly became DEGRADED even though the identity count remained 15/15.
7. Stage3 correctly rejected degraded S02; simply whitelisting S02 would hide a materially stale planning-GW identity.

The stale identity was not metadata-only. The later explicit GW6 state replaces M.Sangaré (565) with Pascal Groß (124).

## Existing bounded repair on current main

Current main already contains the required supportable identity evidence through commit:

`13d527fb4d6b22c831b4ce49ceeae499229df1ac`

The current `FPL_MASTER_STATE_V12.json` binds the post-transfer identity as:

- `status=USER_CONFIRMED_CURRENT`
- `explicit_user_confirmation=true`
- `explicit_user_confirmed_at=2026-09-23T05:54:41+00:00`
- `applicable_planning_gw=6`
- `evidence_source_class=USER_CONFIRMED`
- `evidence_basis=EXPLICIT_USER_CONFIRMED_CURRENT15`
- 15 unique players
- identity-only note; private finance is not persisted or inferred.

The existing reconciliation path already recognizes this evidence as `CURRENT_VALID` for planning GW6. Therefore no production selector patch is required on this branch.

## Private auth policy

Private authentication is not required to establish CURRENT15 when an independently supportable current identity exists, including explicit user-confirmed identity. Private authentication remains separate for bank, purchase/sell values, chips, free transfers, and other private facts.

The regression tests require identity-only confirmation to leave those private fields unavailable rather than fabricate them.

## Human-facing failure is a separate issue

Run `35979672473` also records:

`GOVERNED_RANK20_RANK_MISMATCH=S12:1;GOVERNED_RANK20_RANK_MISMATCH=S13:1`

That is the direct `HUMAN_FACING_QA` failure in this occurrence. It must not be attributed to S02. S02 closure and human-facing closure are separate acceptance checks.

## Regression tests

`tests/test_s02_current15_closure.py` locks three invariants:

1. explicit planning-GW6 USER_CONFIRMED exact15 outranks stale public GW5 identity even when private auth is expired;
2. without such current confirmation, public GW5 remains a stale fallback and finance stays disallowed;
3. identity-only confirmation cannot fabricate bank, purchase/sell values, chips, or free transfers.

## Merge posture

Do not merge from this workstream yet.

PR #716 currently changes `v12_deep_delivery.py` and `v12_integrated_report_runner.py`. This branch intentionally avoids those files and acts only as a bounded regression/evidence lock. Re-read latest main and reconcile with #716 after that workstream reaches its own closure gate.
