# P0 original August source discovery and full-master public-first fix

Audit date: 15 October 2026. Baseline immutable production main: `2af2b285e997eb9d80ebc47a598f3a4df98132a6`.

## Earlier archived source candidates: NEVER automatically admit

Newly inspected original Git commit `8d6c76e7d35ee5332f6d73a2bdc9822d9e62f92c` has Git committer timestamp `2026-08-25T22:33:38Z`, before Official FPL GW2 deadline `2026-08-28T17:30:00Z` and GW3 deadline `2026-09-04T17:30:00Z`. It postdates GW1 deadline `2026-08-21T17:30:00Z`. Original immutable blob identifiers:

| Archived path | Original Git blob SHA1 | Captured content/limits |
| --- | --- | --- |
| `data/gw/01.json` | `fe8db20e95fd5a5a841463f0b094051f4e108c41` | Generated `2026-08-25T18:46:28Z`; records Official bootstrap/fixtures/event status HTTP 200, post-GW1 summary |
| `data/universe.json` | `378fab82877fc26a3c26caff0c8685e7a040bc8d` | GW1-era player identity/availability/aggregate minutes; not verified per-fixture starts |
| `data/stats/playermatchstats_gw1.json` | `9b3f0321293bf940246932a33af2326c533047a2` | 399 GW1 FPL-Core-Insights match-stat rows; source fetched `2026-08-25T12:33:22.335571Z`; provider player-ID bridge to Official still unverified |
| `data/stats/vaastav_gw1.json` | `c3da0a51c9d05d0e13bcb6fa42557747a1506af7` | 599 rows marked `SEASON_SNAPSHOT_FALLBACK`, *not* actual GW1 match rows |
| `data/history.jsonl` | `878766c9e94d8c6097482701c3cc264cc113cb9e` | 25 original Aug25 report records; includes personal account context, do not mirror into public calibration audit |

Original SHA1 values are Git-object identity witnesses, not an independently recomputed SHA256 attestation. No archival source-as-of PASS was minted. This earlier V3/V4-era data remains read-only historical discovery: **V6 remains the only factual authority** and cannot be retroactively replaced with legacy payloads. Match finalization timing, complete Official player-selection evidence, source identity mapping and independent SHA256 receipt must be verified before any row is eligible for `verified_source_archive` and `walk_forward_pstart_validate()`.

| GW | Original predeadline candidate | Historical source-as-of disposition |
| --- | --- | --- |
| GW1 | No source-before-deadline found in inspected August GitHub Actions/objects | HISTORICAL_AS_OF_UNAVAILABLE |
| GW2 | 25 Aug source snapshot, GW1 match rows advisory only | CANDIDATE_UNVERIFIED, NOT_ADMITTED |
| GW3 | 25 Aug source snapshot but no later verified GW2 match-level finalization from this archive | CANDIDATE_UNVERIFIED, NOT_ADMITTED |
| GW4 | V6 source blobs 8 and 9 Sep, original SHA256 PASS | PARTIAL, original match-level training/finalization missing |
| GW5 | V6 12 Sep original SHA256 PASS | PARTIAL, original match-level training/finalization missing |
| GW6 | V6 19 Sep original SHA256 PASS | PARTIAL, original match-level training/finalization missing |

## Public-first full-master corrective change

Controlled full-master prefetch with `public_core_complete=true`, `personal_requested=true`, `authenticated_personal_deferred=true` and `authenticated_personal_required_for_public_green=false` previously returned `PREFETCH_FAILED` despite successful public collection. The canonical V6 classifier now returns **PREFETCH_PUBLIC_FIRST** in that explicit condition. Fail closed when public core fails, authenticated deferral was not actually recorded, personal was not requested, or policy makes protected authentication mandatory. Never infer `AUTH_AVAILABLE`, bank, FT, purchase/selling values, `PREFETCH_FULL` or PRICE READY_FULL from this source classification alone.

Regression extends an existing public-first test without adding new collected pytest IDs. CI is code verification only; a fresh exact-occurrence production prefetch and original private readback remain separately required. Protected OIDC /me and /my-team and Wave3 genuine 12/12 remain independent acceptance gates.

## Hard boundaries

No modification to PR #809, single ChatGPT scheduler, frozen GW7 forecast, Stage3, P1.7, V12_PLAYER_MINUTES, correlated MC500K, source identity crosswalk, or retrospective source-as-of status. No backdated natural or archived evidence.

Change timestamp: 2026-10-15T05:00:00+07:00
Documentation sync: UPDATED
