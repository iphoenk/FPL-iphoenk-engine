from __future__ import annotations

from pathlib import Path

from .registry import load_registry

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "docs" / "V6_SOURCE_CONTRACT_GENERATED.md"


def render_source_contract() -> str:
    registry = load_registry()
    activation = dict(registry.get("activation") or {})
    active_ids = [str(source["id"]) for source in registry.get("sources") or []]
    disabled = dict(activation.get("disabled_sources") or {})
    reference = dict(activation.get("reference_only_sources") or {})
    required = list(activation.get("required_active_sources") or [])
    overrides = list(registry.get("source_overrides_applied") or [])

    lines = [
        "# V6 Source Contract (Generated)",
        "",
        "> Generated from the resolved V6 registry. Do not hand-edit counts or source lists.",
        "",
        "| Metric | Count |",
        "|---|---:|",
        f"| Configured source definitions | {activation.get('base_source_count', len(active_ids) + len(disabled) + len(reference))} |",
        f"| Active scheduled sources | {activation.get('active_source_count', len(active_ids))} |",
        f"| Disabled sources | {activation.get('disabled_source_count', len(disabled))} |",
        f"| Reference-only sources | {activation.get('reference_only_source_count', len(reference))} |",
        f"| Required active sources | {activation.get('required_active_source_count', len(required))} |",
        f"| Temporary source overrides | {len(overrides)} |",
        "",
        "## Active scheduled sources",
        "",
        *[f"- `{source_id}`" for source_id in active_ids],
        "",
        "## Disabled sources",
        "",
        *[f"- `{source_id}`: {reason}" for source_id, reason in disabled.items()],
        "",
        "## Reference-only sources",
        "",
        *[f"- `{source_id}`: {reason}" for source_id, reason in reference.items()],
        "",
        "## Required active sources",
        "",
        *[f"- `{source_id}`" for source_id in required],
        "",
        "## Governance",
        "",
        "- Stable provider contracts belong in the canonical registry/additions layer.",
        "- `source_overrides.json` is temporary repair-only and lifecycle-governed.",
        "- Activation state comes only from `config/v6/source_activation.json`.",
        "- V6 remains data-only; this generated document conveys acquisition configuration, not FPL intelligence.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    expected = render_source_contract()
    current = DEFAULT_OUTPUT.read_text(encoding="utf-8") if DEFAULT_OUTPUT.exists() else ""
    if current != expected:
        print("V6 generated source contract is stale")
        return 1
    print("V6 generated source contract is current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
