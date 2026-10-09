# V12 Injury / Fitness / Availability Evidence

## Ownership

The V12 injury layer is an evidence-normalization and categorical-resolution layer only.

Pipeline:

```text
source observation
  -> atomic claim + claim-level provenance
  -> root-claim deduplication
  -> domain-aware normalization
  -> active / superseded / historical evidence
  -> target-GW categorical gw_availability
  -> feature adapter
  -> existing V12_PLAYER_MINUTES P(start)/xMins owner
  -> lineup / captain / transfer optimizer
```

It does not create a second P(start) model, xMins model, optimizer, factual plane,
or publisher.

## Semantic contract

Every derived availability state is target-aware:

- `target_gw`
- `target_fixture_id` where known
- `derived_at`
- `evidence_cutoff_at`

`gw_availability` is categorical only:

- `AVAILABLE`
- `LIKELY_AVAILABLE`
- `DOUBT`
- `STRONG_DOUBT`
- `OUT`
- `UNKNOWN`

It answers whether a player is medically/operationally available for the target
fixture. It does not answer whether the player will start.

Therefore `AVAILABLE + Pstart=0.58` is valid when tactical rotation, competition
for places, or expected minutes reduce start security.

## FPL flags

Official FPL 25/50/75 flags are preserved as `FPL_STATUS` observations. They are
never divided by 100 and used as P(start), P(available), or xMins.

FPL status/news may still be shown as evidence, but medical diagnosis, body part,
severity, or return timeline is never inferred from the percentage.

## Claims and provenance

Each normalized claim preserves both `raw_claim` and `normalized_claim`, plus:

- claim/root IDs and republication state;
- event/observation time;
- source URL/type/authority;
- claim domain and domain-specific authority;
- evidence polarity;
- medical/operational fields where explicitly sourced.

`injury_confirmed=NO` requires affirmative no-injury evidence. Missing diagnosis
remains `UNKNOWN`.

A later full-training or match-appearance claim may supersede an older
availability concern without rewriting the historical fact that an injury was
previously confirmed.

Republished versions of one root claim do not increase independent evidence
count.

## Model integration

The evidence resolver never emits P(start).

The existing `src/engines/v12_player_minutes.py` owner consumes only normalized
features. `OUT` can close the hard operational gate only when target-specific
high-authority evidence explicitly confirms unavailability.

`DOUBT` and `STRONG_DOUBT` may contribute a bounded model signal inside that
same P1.1 owner. `AVAILABLE`, `LIKELY_AVAILABLE`, `UNKNOWN`, and confidence
labels are not direct start-probability aliases.

## Reporting and observability

User-facing DEEP output remains bounded. Player rows expose categorical
availability and a concise warning only when material.

S17 exposes aggregate injury/availability evidence health:

- players with evidence;
- active/stale/conflicting/root-republication counts;
- categorical availability counts;
- resolver/model ownership;
- explicit proof that FPL flags are not direct probabilities.

Raw claim dumps remain in technical projection/evidence artifacts, not the
visible report.
