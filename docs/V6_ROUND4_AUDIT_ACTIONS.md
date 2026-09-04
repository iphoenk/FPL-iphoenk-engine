# V6 Round 4 Audit Actions

Source review: `AUDIT V6 ROUND3 DAN REKOMENDASI.md`
Base: `88f9c39` (PR #419 merged)

## Executed in V6 scope

- Move authoritative V6 cron away from `:00/:12` to `:05/:35`.
- Add `config/v6/schedule_policy.json` as the operational schedule/recovery contract.
- Make the workflow classifier read schedule policy instead of duplicating cron literals.
- Add contract tests that require GitHub `on.schedule` literals to match schedule policy exactly.
- Restore `workflow_dispatch` only as governed emergency recovery.
- Restrict manual recovery to repository owner + explicit audit reason + confirmation phrase.
- Keep manual recovery non-authoritative: it does not advance the scheduled baseline, does not satisfy a missed scheduled slot, is manifested AMBER, and remains invalid to the normal V6 consumer until a real scheduled cycle succeeds.
- Preserve dedicated V6 GitHub App publication and the governed `runtime-data-v6` ruleset.
- Synchronize V6 architecture documentation with the new cadence and recovery semantics.

## Verified collision analysis

The current V3 runtime/package wake-up set is `:02,:07,:12,:17,:22,:27,:32,:37,:42,:47,:52,:57`, plus logical/precompute slots around `:15/:30`. V4 timing probe owns `:00`. Therefore `:05/:35` removes the exact V4 `:00` collision and does not overlap the listed current V3 cron minutes.

## Deliberately not executed

The external recommendation to reduce V3 runtime/package cadence is cross-scope and is not required to create collision-free V6 slots. It remains a separate V3 capacity/efficiency decision and must not be changed as a side effect of a V6 incident repair.

## Production acceptance

Do not declare this round production-proven from code/CI alone. After merge, require natural GitHub `schedule` evidence on `:05/:35`, governed dedicated-App publication, and consecutive healthy logical slots with no unexplained missed cycle. Manual recovery never substitutes for this proof.
