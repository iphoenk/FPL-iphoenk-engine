"""Compatibility facade for the canonical runtime-control implementation."""
from .domains.control_plane import runtime_control as _impl
from .operational_ledger import build_operational_slots

globals().update({name: getattr(_impl, name) for name in dir(_impl) if not name.startswith("__")})

if __name__ == "__main__" and hasattr(_impl, "main"):
    raise SystemExit(_impl.main())
