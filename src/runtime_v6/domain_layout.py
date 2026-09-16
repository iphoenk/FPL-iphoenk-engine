from __future__ import annotations

"""Canonical ownership map for Wave 14 V6 runtime domains."""

DOMAIN_MODULE_MAP: dict[str, tuple[str, ...]] = {
    "acquisition": (
        "adapters",
        "collector",
        "http_client",
        "official_fpl_client",
        "polling",
        "source_native",
        "noauth_source_native",
        "ffscout_public",
        "normalizer",
        "rotowire_normalizer",
    ),
    "identity": (
        "entity_scope",
        "identity",
        "identity_scope",
        "identity_coverage",
        "verified_bridges",
        "verified_crosswalks",
    ),
    "publication": (
        "artifact_catalog",
        "artifact_migration",
        "artifact_provenance",
        "production_validate",
        "publish_integrity",
        "store",
        "registry",
    ),
    "control_plane": (
        "control_plane",
        "temporal",
        "schedule_policy",
        "scheduled_report_slot",
        "runtime_control",
        "workflow_control",
        "scheduler_watchdog",
        "scheduler_recovery",
        "legacy_scheduler_compat",
    ),
    "report_plane": (
        "consumer",
        "delivery_integrity",
        "report_contract",
        "report_compute",
        "report_delivery",
        "report_prefetch",
        "report_qa",
        "report_recovery",
        "report_recovery_closeout",
        "report_trigger",
        "prefetch_contract",
        "personal_prefetch",
        "league_prefetch",
    ),
    "observability": (
        "current_health",
        "health",
        "operational_ledger",
        "operational_reliability",
        "player_observation",
        "report_observability",
    ),
    "governance": (
        "architecture_independence_validate",
        "authority_contract",
        "season_contract",
        "security",
        "source_contract_doc",
        "source_policy",
    ),
}

DOMAIN_NAMES = tuple(DOMAIN_MODULE_MAP)
MODULE_DOMAIN = {
    module_name: domain
    for domain, module_names in DOMAIN_MODULE_MAP.items()
    for module_name in module_names
}
