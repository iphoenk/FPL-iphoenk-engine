# FPL iphoenk Engine v3.39.0

> **Last runtime/documentation sync:** `2026-10-06T16:10:00+07:00`

A governed Fantasy Premier League decision-support engine combining public football facts, probabilistic modelling, full-universe discovery, squad optimisation, Monte Carlo, mini-league context, and private report delivery.

> **V6 establishes factual truth. Canonical V12 interprets those facts for FPL decisions. Manager-specific state and reports remain private.**

## Core architecture

`Official/Public Data → V6 Facts → Canonical V12 → Optimisation → WAIT / PREPARE / ACT → Reports`

- **V6 factual plane:** governed facts, freshness, fixtures, prices, and source evidence.
- **Canonical V12:** xMins, probability, tactics, full-universe scanning, optimisation, Monte Carlo, and decision semantics.
- **Private delivery:** manager-specific squad state, scenarios, mini-league context, decisions, and full reports.

Canonical FPL entry identity is repository-configured. Authenticated personal acquisition is an optional enrichment for private/current finance facts; when auth is intentionally unavailable, governed Official FPL submitted-picks or explicit owner evidence may still support Current15 identity, while auth-only finance fields remain unavailable.

## Reports

**DEEP** is the full planning report, **PRICE** handles price/timing, **DEADLINE / FINAL** is the final pre-deadline checkpoint, and **MATCH** covers post-deadline and matchday monitoring.

Primary schedule: **DEEP 04:30 / 12:30 / 21:30 Asia/Jakarta** and **PRICE 23:30 Europe/London**. Deadline and Matchday use governed checkpoints.
GitHub Actions `v6-natural-data-ingestion.yml` is the sole recurring natural scheduler. It uses four staggered cron arrivals per hour (`:13/:28/:43/:58`) that share one logical hourly slot and deduplicate before acquisition. The same workflow routes fixed DEEP/PRICE checkpoints with a bounded 3-minute-early / 60-minute-late window; the former ChatGPT issue-title transport is historical compatibility only.

`fpl-external-clock-fallback.yml` is dispatch-only and has no cron. An authenticated external cloud clock may invoke it when GitHub scheduled events are unavailable; it uses `master_orchestrated` for exact operational-slot recovery and the existing occurrence orchestrator for due reports. External fallback never counts as natural scheduler proof or natural acceptance.

Occurrence commands are exact-time only: future report slots are rejected, and private serving state created before its claimed occurrence cannot satisfy idempotent reuse.

## DEEP decision-content delivery barrier

DEEP is occurrence-bound, provenance-aware, privacy-safe, and may degrade explicitly when evidence is unavailable rather than inventing data. Its visible renderer is presentation-lock driven: the header carries report identity only, S04 owns material news/developments, S14 is bounded to optimizer/search evidence, S15 owns decision-evidence quality, S17 owns technical health/freshness/lineage, and mini-league context uses the dynamic Competitive Window.

## PRICE human-facing delivery barrier

PRICE follows the same factual/provenance boundary and never invents unavailable manager state or decision output.

## Captaincy

Captaincy is now distribution-first: S08 compares legal selected-XI candidates using canonical P1.3B one-GW return distributions, treats Phaul as the existing P(points ≥ 10) tail rather than a second weighted signal, and classifies the football frontier as CLEAR, CLOSE, or FRAGILE. Mini-league LEAGUE/Competitive Window exposure may break only a CLOSE football decision when standing-gap context is complete; EO never overrides a clear football edge, and nonnumeric competitive EO is treated as unavailable rather than coerced. S15B is evidence-only, while S08, S18, and S19 consume one canonical C/VC decision. Cross-player joint correlation and candidate-specific relative-points captain MC are not currently fabricated when unavailable.

## Governance

The engine scans the **full eligible FPL universe**, separates facts from inference, preserves uncertainty, and keeps manager-specific state private.

**Current-state authority** comes from governed CI/runtime evidence and `runtime-data/data/runtime_manifest.json`; this README and `MASTER_TASK_LIST_V3.md` are only a **human-readable projection**.

Detailed methodology, formulas, evidence weighting, privacy, scheduler, delivery architecture, presentation contracts, P4/P6, cache behaviour, and performance governance live under `docs/v12/`.

Delivery authority: `docs/v12/FPL_V12_DELIVERY_ARCHITECTURE_PLAN_REV6.md`  
Schedule authority: `config/delivery/v12_delivery_schedule.json`

> **Caveat:** this is a decision-support system, not an oracle. FPL outcomes remain stochastic and source evidence can change quickly.
