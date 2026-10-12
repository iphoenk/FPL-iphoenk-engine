# S08 canonical PMF shared-world closure

Change timestamp: 2026-10-12T15:25:00+07:00

## Root cause

The production captain frontier sent canonical P1.3B point PMFs to the shared-world C/VC simulator, but the simulator unconditionally required a separate goalkeeper event-calibration package. That package is not part of the canonical PMF contract, so a valid selected-XI captain surface degraded to `UNAVAILABLE`. The convergence result also exposed only an internal availability label, while the CLOSE decision gate required an explicit `PASS`.

## Repair

- Preserve strict goalkeeper-event validation as the default direct simulator contract.
- Add an explicit canonical-PMF mode for the frontier; it validates every point PMF and `p_dnp`, but does not synthesize clean-sheet, conceded-goal, save, bonus or penalty-save events.
- Emit per-goalkeeper calibration status and `missing_event_model_is_not_synthesized`.
- Emit a separate convergence `gate_status: PASS` while retaining the existing `status: AVAILABLE_FOR_EXISTING_GATE` compatibility field.
- Let CLOSE decisions consume that explicit gate without changing MC path count, seed, universe, mini-league simulation, or route ownership.

## Regression

The strict missing-calibration regression remains PASS. New tests prove the canonical PMF route is available at exactly 500,000 paths, exposes the explicit not-required calibration status, and produces deterministic convergence evidence.

Documentation timestamp: 2026-10-12T15:25:00+07:00
