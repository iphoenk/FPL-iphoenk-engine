# P0 P(start) historical-as-of evidence audit, 14 October 2026

## Scope and trust boundary

This is an inventory of inspected GitHub objects, **not** a declaration that every possible archive was exhausted. GitHub commit timestamps, file SHA, payload timestamp, Official FPL deadline and receipt need to match the original predeadline observation. Current-cycle V6 refresh and postdeadline backfills cannot qualify retroactively. Do not replace a missing `finalized_at` with `source_checked_at`, `effective_at`, a report slot or today's timestamp.

## Verified observations

1. Production main at audit start: `493d6315c7efef7b70f85361a858ffd959ed1c15` (PR #1065 merged). Semantic delivery, repository naming and governance push workflows succeeded. This is CI evidence, **not** P(start) calibration or natural DEEP acceptance.
2. Active `runtime-data-v6` branch at the observed checkpoint: `e9be5700ac60c0041952391e38d7f9d96b9fdaa5`, commit timestamp `2026-10-14T01:35:30Z`, message `data(v6): atomic hourly snapshot 38496501313`. GitHub Git Commit API reports **zero parents**. Consequently the active branch's reachable commit ancestry cannot by itself establish historical GW1–GW6 source snapshot timing.
3. Private `fpl-reports-private/reports/2026-27` currently exposes `gw_6` and `gw_7`, not historical GW1–GW5 report folders. The earliest inspected private commit before 26 September is not present; commits begin appearing on 26 September. This does not prove other repositories, unreachable Git objects or expired Actions artifacts never contained evidence.
4. Inspected Actions artifacts for run IDs `33452812166` (31 August), `35670033021` (21 September), `36276649162` and `36276767226` (26 September) returned empty inventories. A later genuinely natural run `38496501313` has V6 publication and integrity artifacts, but their October creation cannot prove August/September source-as-of.
5. Private DEEP `2026-10-14T06:05:21+07:00` contains 667-player GW1–GW6 historical coverage, and P(start) individual selection inputs for 15/15 OUR15. Its S02 reports `RETROSPECTIVE_DIAGNOSTIC_ONLY`, `predeadline_source_lineage=UNVERIFIED`, `MODEL_RESOLUTION=LIMITED_RESOLUTION`, 3191 samples across five folds, and 12/15 identical P(start)=0.834.

## GW1–GW6 source-as-of disposition

| Target | Retrospective normalized player facts | Archived independently verified original predeadline inputs | Disposition |
| --- | --- | --- | --- |
| GW1 | Available within six-GW historical report | Not established by inspected artifacts | HISTORICAL_AS_OF_UNAVAILABLE |
| GW2 | Available within six-GW historical report | Not established by inspected artifacts | HISTORICAL_AS_OF_UNAVAILABLE |
| GW3 | Available within six-GW historical report | Not established by inspected artifacts | HISTORICAL_AS_OF_UNAVAILABLE |
| GW4 | Available within six-GW historical report | Not established by inspected artifacts | HISTORICAL_AS_OF_UNAVAILABLE |
| GW5 | Available within six-GW historical report | Not established by inspected artifacts | HISTORICAL_AS_OF_UNAVAILABLE |
| GW6 | Available within six-GW historical report | Historical report exists, but complete independently verified source-as-of chain not established | HISTORICAL_AS_OF_UNAVAILABLE |

The existing five retrospective folds are diagnostic only. Before promoting any old GW fold, audit **each individual matching source snapshot** against original deadline, immutable GitHub object (commit/blob), repository/path, source identity, original recorded capture/finalization timestamp, payload SHA256 and pipeline receipt. Explicitly reject overwritten branch pointers, orphaned source objects without a trusted original timestamp, and fabricated historical captures.

## Candidate prospective GW7 baseline

There are predeadline DEEP report objects under the private GW7 occurrence directories, including `reports/2026-27/gw_7/20261014_060521_plus_0700`. They are evidence **candidates**, not a completed canonical full-universe P(start) prospective freeze: no independent proof in this audit ties a per-player frozen baseline/individualized forecast, original V6 input receipt, SHA256 and Official FPL GW7 deadline to an immutable admission record. Only after validation may one of these be admitted. Preserve old revisions; never overwrite prior GW7 frozen predictions.

## Production diagnostics and gate separation

Latest S02 numerical retrospective diagnostics: starter Brier 0.242833 baseline vs 0.235817 individualized; log loss 0.673453 vs 0.658842; xMins MAE 35.289972 vs 34.842745, paired sample 3191, `NONINFERIORITY=PASS` as a retrospective diagnostic. It is not a prospective holdout PASS. Position, team and DNP/cameo scoring must remain visible and independent. `READY_FULL` only verifies report delivery, not calibration, model resolution or source-lineage readiness.

## Remaining production acceptance work

1. Exhaust additional authenticated/retained sources of *original* archived predeadline V6 artifacts, especially historical Actions ZIPs and durable signed receipts. Do not infer absence globally from empty sampled runs.
2. Implement within the existing governed V6 production/DEEP occurrence a **write-once** full-universe GW7 predeadline input and forecast archive. Bind Official deadline, exact slot, V6 source identities and per-source SHA256, immutable Git commit, both baseline and individualized predictions, all metrics/probabilities and model/config fingerprint. Store under unique occurrence identity in existing private publication path; no duplicate scheduler or novel mathematical owner.
3. Build a stricter verified archival witness for `walk_forward_pstart_validate` backed by original Git objects, rather than accepting self-declared timestamps or a token `verified=true`. If no witness exists, retain `HISTORICAL_AS_OF_UNAVAILABLE`.
4. Settle only after official GW completion; compare paired starter Brier/log loss, xMins MAE, DNP/cameo and reliability by GK/DEF/MID/FWD and club. Require 667-player universe coverage, sample minimums, position noninferiority and zero leakage.
5. Keep `READY_FULL`, `MODEL_RESOLUTION`, `CALIBRATION`, `SOURCE_AS_OF`, `NONINFERIORITY`, and true natural occurrence independently gated. No promotion without remote readback of exact occurrence.

## Explicit nonchanges

No changes to PR #1065, PR #809, V6 data authority, V12_PLAYER_MINUTES mathematics, correlated MC500K, eight legal formations, Stage3 temporal integrity, or ChatGPT scheduler. Role/coach/fixture-fit evidence remains advisory unless independently calibrated.

## Addendum: additional public Actions retention check, 14 October 2026

The GitHub API reports empty artifact inventories for inspected completed V6 hourly acquisition runs `34725699713`, `34722950239`, `34720145902` (12 September) and `35476739571` (19 September), and inspected skipped runs `36198244096`, `36156578313` (25 September). Previously sampled `33452812166` and `35670033021` also return empty inventories. The public repository main tree at original 25 September commit `31c912345d17b9225cfbe2b6dae5c2de3649a6e6` contains no `data/v6` source snapshot blobs. The private repository's inspected commit history starts on 26 September, and early GW6 manual captures are **team state**, not full-player predeadline model inputs.

These results narrow the archive recovery search. They do not prove that unreachable Git objects, other older workflow artifacts, GitHub caches or additional trusted archives never existed. No GW1–GW6 fold may be promoted without authentic immutable predeadline readback, original source SHA256, source identity, official deadline and independent original finalization/first-seen evidence. Keep historical gate UNAVAILABLE where evidence is absent. Historical snapshots cannot be recreated retroactively from current Official FPL data.

Change timestamp: 2026-10-14T15:23:39+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-14T15:23:39+07:00

## Recovery discovery: original V6 Git objects survive force-updated runtime branch

Read-only GitHub Actions **logs**, unlike their expired/empty artifact inventories, preserve the original published runtime commit IDs. GitHub Git Commit and Tree APIs independently returned both original root commits and their original trees:

| Original V6 run | Original commit | GitHub recorded commit time (UTC) | Original Official FPL blob (Git SHA-1) | Catalog Official FPL SHA256 | Admission |
| --- | --- | --- | --- | --- | --- |
| `34725699713` | `d2d9ddbfc6292964240a03d60c30dbba62c3ac1f` | `2026-09-12T23:33:28Z` | `8eed445a0080b0dd0265b9126a43997b0d53b305` | `cd20e4028b4e390231fece33b74b880c36d242b132b7d6e6c1ecb8e66e85057e` | SOURCE_CANDIDATE_ONLY |
| `35476739571` | `41b95421cba8fe70c94d0769e039f2208ede6b3c` | `2026-09-19T23:40:44Z` | `96db450a284deffa930084313c08485d97f2b3ea` | `186077472a3514e82f860be1f7af3ac147f36cee479fa4050e3183f0b74dbfbb` | SOURCE_CANDIDATE_ONLY |

Original `data/v6/evidence/artifact_catalog.json` was read back from each original commit. It records `official_fpl` source snapshot IDs, effective timestamp, production run ID, and the SHA256 above. Original `data/v6/normalized/canonical_fixtures.json` also read back successfully: 380 fixtures (10 per GW) with original FPL fixture IDs. This materially strengthens the archive audit: zero retained Actions ZIPs does **not** imply original Git objects were lost. September snapshots may support some **later** training folds, subject to independent deadline and all source-row checks, but cannot establish GW1–GW4 predeadline evidence on their own.

The large Official FPL source blobs were confirmed as immutable Git tree entries, but their complete payload bytes were not independently rehashed during this audit. SHA256 values currently come from the original committed catalog. Before admitting any fold, an approved verifier must read the exact original blob bytes, compute SHA256 independently, bind original commit/run timestamp and original source IDs, verify each required previous-GW finalized player/fixture row and compare the actual target GW deadline. Do not promote the catalog's own digest or commit timestamp alone as complete proof. GW1–GW6 overall remains `HISTORICAL_AS_OF_UNAVAILABLE` pending row-level admission.

Change timestamp: 2026-10-14T15:23:39+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-14T15:23:39+07:00

### Additional original September 8–9 objects for the GW4 candidate pool

Two earlier original V6 root commits also survive and were independently returned by GitHub Git Tree APIs. The original `artifact_catalog.json` was read back at each exact commit and contains the corresponding original Official FPL source snapshot identities:

- Natural run `34286506638` published `ed5c910aee9bf808aa7007a080da3b0654338841` at 2026-09-08T22:34:02Z; original Official FPL Git blob `f64a1f1836b135d8abbfcf17bfbc8fdd640be894`, catalog SHA256 `cc11e734bd93c200e0fb8920e65b843cd736e42250804870094ec0167ff5e56c`.
- Natural run `34417093599` published `e7b7ded8aebc19a115ddbf2ef16946986c26bdb9` at 2026-09-09T23:29:05Z; original Official FPL Git blob `4261175f3e25bdc86304ef74df291ddaa431e256`, catalog SHA256 `768e11092ac6a2c99199ec9597b753632a0afc08caa7c82c74cd0cec7ae57176`.

These are **potential** original input snapshots for evaluating a later target GW, not confirmed source-as-of admission for any GW. Existing retrospective match rows must be compared to the original archived bytes and the actual target deadline before issuance of a trusted per-row witness. Do not extrapolate earlier GW2/GW3 provenance from a September archive.

Change timestamp: 2026-10-14T15:23:39+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-14T15:23:39+07:00

## Original Official FPL source byte-level SHA256 verification (14 October 2026)

**This newer readback supersedes the earlier 'large blobs not independently rehashed' observation above.** The exact archived Git blob bytes were fetched by blob SHA from GitHub Git object storage, re-encoded to UTF-8, independently hashed using SHA256, and compared with the SHA256 on each archived original `data/v6/evidence/artifact_catalog.json` read from its original commit. All four raw source files independently matched their original recorded SHA256.

| Original run | Original root commit | Original Git blob SHA-1 | Raw file bytes | Independently verified SHA256 | Result |
| --- | --- | --- | ---: | --- | --- |
| 34286506638 (8 Sep) | `ed5c910aee9bf808aa7007a080da3b0654338841` | `f64a1f1836b135d8abbfcf17bfbc8fdd640be894` | 5,785,820 | `cc11e734bd93c200e0fb8920e65b843cd736e42250804870094ec0167ff5e56c` | SOURCE_BLOB_SHA256_VERIFIED |
| 34417093599 (9 Sep) | `e7b7ded8aebc19a115ddbf2ef16946986c26bdb9` | `4261175f3e25bdc86304ef74df291ddaa431e256` | 5,787,551 | `768e11092ac6a2c99199ec9597b753632a0afc08caa7c82c74cd0cec7ae57176` | SOURCE_BLOB_SHA256_VERIFIED |
| 34725699713 (12 Sep) | `d2d9ddbfc6292964240a03d60c30dbba62c3ac1f` | `8eed445a0080b0dd0265b9126a43997b0d53b305` | 5,861,271 | `cd20e4028b4e390231fece33b74b880c36d242b132b7d6e6c1ecb8e66e85057e` | SOURCE_BLOB_SHA256_VERIFIED |
| 35476739571 (19 Sep) | `41b95421cba8fe70c94d0769e039f2208ede6b3c` | `96db450a284deffa930084313c08485d97f2b3ea` | 6,006,803 | `186077472a3514e82f860be1f7af3ac147f36cee479fa4050e3183f0b74dbfbb` | SOURCE_BLOB_SHA256_VERIFIED |

The original source payload `data.bootstrap.json.events` binds Official GW4 deadline to `2026-09-12T12:30:00Z`, GW5 to `2026-09-18T17:30:00Z`, and GW6 to `2026-10-10T10:00:00Z`. Original 8 Sep snapshot has 654 players, ten finished official fixtures for each of GW1–GW3, zero finished GW4 fixtures, and original observation timestamp `2026-09-08T22:33:45.978263Z`. Original 9 Sep also has 654; 12 Sep has 657; 19 Sep has 667. The 12 Sep file was captured **after** GW4 deadline, not eligible as GW4 predeadline input; the 19 Sep file was captured **after** GW5 deadline, not eligible as GW5 predeadline input. Their source-as-of eligibility is for later GW targets only.

**Strict scope of PASS:** `SOURCE_BLOB_SHA256_VERIFIED=4/4` attests to original **byte integrity**, not the historical backtest's original per-player inputs, model as-of registration, training provenance, or predictor performance. The existing 3,191 retrospective samples cannot be given `historical_asof_status=PASS` from these four blobs alone. Confirm that each paired player-match input existed in the same admissible archive before the target deadline and verify per-fold row linkage and model version; otherwise `HISTORICAL_AS_OF_UNAVAILABLE` remains. No historical forecast is fabricated.

Change timestamp: 2026-10-14T08:52:39+00:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-14T08:52:39+00:00
