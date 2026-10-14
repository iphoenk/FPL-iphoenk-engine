# P0 RotoWire source-to-official candidate mapping audit, GW7

Read-only audit, generated from original \`runtime-data-v6\` source objects observed on **14 October 2026 18:30 WIB**. This change is a **mapping worklist**, not a verified player crosswalk or a calibrated P(start) feature.

## Immutable inputs and mapping output

- RotoWire normalized Git blob: \`ba531b12ab4cfb323297e30d0e0cc1273052bce7\`
- Official FPL source Git blob: \`d4cf1bac655295a0b0196dedebfcaa53f38a16f0\`
- RotoWire effective_at: \`2026-10-14T11:30:29.062434+00:00\`
- GW7 official deadline: \`2026-10-17T10:00:00Z\`
- Canonical universe: **667** Official FPL players.
- Input: **220** RotoWire lineup rows + **102** availability rows; **312** distinct provider-native IDs.
- Candidate discovery: **299/322 rows**, representing **289 distinct native IDs**, have a unique Official FPL name-and-current-club candidate. Another **23 native IDs** lack a uniquely matching exact-normalized player name in the same Official FPL club.
- **0** RotoWire player links are marked \`EXACT\` or \`VERIFIED_MANUAL\`. **0** numeric RotoWire features are applied to V12_PLAYER_MINUTES. No existing immutable GW7 forecast is rewritten.
- Fixture checks: **10** unique home/away + exact New York ET-to-UTC kickoff matches identify Official GW7 fixtures; **1** source fixture is \`UNKNOWN|UNKNOWN|UNKNOWN\` and cannot be validated; **1** fixture (Ipswich Town v Nottingham Forest, 23 October) belongs to **GW8**, not GW7.
- Hull City and Coventry City **are listed as Official FPL 2026/27 clubs**. They are not data-quality failures on their own.

The exact individual worklist is in [ROTOWIRE_GW7_IDENTITY_CANDIDATES_20261014.json](ROTOWIRE_GW7_IDENTITY_CANDIDATES_20261014.json). The reusable read-only builder is [scripts/v6_rotowire_candidate_audit.py](../../scripts/v6_rotowire_candidate_audit.py):

\`\`\`bash
python scripts/v6_rotowire_candidate_audit.py \
  --runtime-data-root . --target-gw 7 \
  --out docs/audits/ROTOWIRE_GW7_IDENTITY_CANDIDATES_REFRESHED.json
\`\`\`

The script must run only against a real original \`runtime-data-v6\` materialization. It **does not** run on schedule, change V6 acquisition or issue #431, or mutate \`config/v6/verified_crosswalks.json\`.

## Why this does not prove MODEL_RESOLUTION

1. A RotoWire native ID is stable provider identity, but matching the displayed **name and club** against FPL is only a discovery candidate. It is not an independently verified provider-native-to-official crosswalk and remains \`identity_status=UNMAPPED\`.
2. A fixture is admitted as the same match only where **both clubs, the season, and the exact UTC kickoff** agree. A GW8 candidate cannot inform GW7-specific expected-lineup context. The unknown fixture remains quarantined.
3. Predicted lineups are an external forecast, not observed historical starter outcomes. Even a crosswalk does not give permission to backfill historical GW1–GW6 selection or to upgrade \`role_start_probability\` without temporal lineage and calibrated evidence.
4. An availability annotation like \`QUES\` or \`OUT\` is not a numerical absence or medical probability. It requires a primary-source crosscheck and predeadline timestamp.
5. The normalized position \`D\`, \`M\`, \`F\` or \`DL/DC/DR\` is a descriptive role from this provider, not a verified manager-specific formation posterior.

## Actual next gate to unlock downstream analysis

For each candidate in the JSON file, find and preserve an independent native-ID bridge, e.g. RotoWire's unique profile ID paired with an independently verified source-native player record and non-name evidence. Verify source/season/team/temporal consistency, conflicts and one-to-one Official FPL code; only then place reviewed exact links in \`config/v6/verified_crosswalks.json\`, as allowed by the existing loader and governance. Re-run V6 normalization to produce real joinable player rows. The existing \`V12_PLAYER_MINUTES\` model must remain the sole P(start)/xMins owner.

Keep these gates separate: \`SOURCE_COLLECTED\`, \`FIXTURE_VERIFIED\`, \`PLAYER_CANDIDATE\`, \`PLAYER_CROSSWALK_VERIFIED\`, \`ASOF_VERIFIED\`, \`FEATURE_CALIBRATED\`, \`MODEL_NONINFERIOR\`, and \`PRODUCTION_READBACK_PASS\`. No candidate-only stage may claim \`MODEL_RESOLUTION_FULL\`.

Change timestamp: 2026-10-14T18:30:29+07:00
Documentation sync: UPDATED
