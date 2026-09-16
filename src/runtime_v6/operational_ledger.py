"""Compatibility facade for canonical operational ledger."""
from .domains.observability import operational_ledger as _impl

# Legacy static-contract marker; canonical ownership remains in domains/observability.
CANONICAL_GOVERNANCE_KEY = "scheduler_observability_only"

def build_operational_slots(*args, **kwargs):
    """Forward the legacy public callable without duplicating ledger logic."""
    return _impl.build_operational_slots(*args, **kwargs)

globals().update({name: getattr(_impl, name) for name in dir(_impl) if not name.startswith("__") and name != "build_operational_slots"})

if __name__ == "__main__" and hasattr(_impl, "main"):
    raise SystemExit(_impl.main())
