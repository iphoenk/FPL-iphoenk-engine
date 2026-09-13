# V6 FFScout Public Player Identity

## Scope

This contract covers only publicly accessible Fantasy Football Scout content acquired without member authentication. V6 remains a data-only platform and has no prediction, xPts, xMins, transfer, captaincy, chip, formation or optimizer authority.

Fantasy Football Scout's public predicted-lineups page renders player avatars using `resources.premierleague.com` URLs whose numeric player media code is the same identity field exposed by Official FPL as `bootstrap.elements.code`.

Example public evidence shape:

`https://resources.premierleague.com/.../players/110x140/154561.png`

The numeric value `154561` is resolved only by exact equality with the unique Official FPL `elements.code` value. Display names are retained as evidence only and are never used as an identity key.

## Deterministic join

`FFScout public player reference -> embedded Premier League media code -> Official FPL elements.code -> Official FPL element_id`

Identity method:

`FFSCOUT_PUBLIC_PREMIERLEAGUE_MEDIA_CODE_EXACT`

Required controls:

- no exact-name authority;
- no fuzzy-name authority;
- duplicate Official FPL codes fail closed;
- unknown embedded media codes remain `UNMAPPED`;
- partial coverage is reported truthfully;
- identity provenance retains the public request id and image URL evidence;
- external identifiers remain attributes, never canonical primary keys.

## Public acquisition

The canonical FFScout source acquires both the public homepage feed and the public `/team-news/` predicted-lineups page. The latter is player-level public editorial/team-news evidence and is not treated as member statistics.

## Member-area boundary

Fantasy Football Scout documents its detailed player/team statistics as Members Area data behind a paywall. V6 must not bypass member authentication or scrape protected member statistics without separately authorised access and an approved acquisition contract.

Therefore this change enables deterministic player-level joining for public FFScout observations. It does **not** claim that premium FFScout statistics are acquired.

If authorised member access is added in the future, it must use a separate secret-backed acquisition contract, preserve this deterministic identity rule, and continue to publish data only.
