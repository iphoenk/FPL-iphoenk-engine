# Evidence metadata
source: cache modules at PR #668 head + inspected Actions artifacts
commit_sha: 03abbdd9e4a1f662d4bb92f588808247d8790892
timestamp_utc: 2026-09-23T13:38:47Z
status: NOT AVAILABLE

Stage2: `V12_STAGE2_DERIVED_CACHE_DIR`; fingerprint includes schema, planning_gw, bootstrap, strength, historical_prior, player_features_payload, player_match_rows, opponent_history_rows/scope, model dependency SHA256s; storage `<root>/<key[:2]>/<key>.pkl`; key/schema/content check, rebuild on miss/corruption.

P1.7: `V12_P17_DECISION_CACHE_DIR`; fingerprint includes schema, optimizer_code_sha256, canonical_v12_revision, ruleset_id, lineup_rules, config, players; same sharded pkl storage; mismatch/corruption recomputes.

MC: `V12_MC_SIM_CACHE_DIR`; fingerprint includes schema, mc_code_sha256, canonical revision, config fingerprint, projection fingerprint, normalized route signature including economics, actual_paths, seed, horizons, selected_route_id, canonical flag, numpy_version; same sharded pkl storage.

Cache byte/file sizes: NOT AVAILABLE. Reason: inspected production Actions artifacts/logs do not serialize cache directory sizes, and a new audit workflow_dispatch could not be launched through the available GitHub tool surface.
