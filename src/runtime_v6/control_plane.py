"""Compatibility facade for the canonical control-plane implementation."""
from .domains.control_plane import control_plane as _impl

globals().update({name: getattr(_impl, name) for name in dir(_impl) if not name.startswith("__")})

if __name__ == "__main__" and hasattr(_impl, "main"):
    raise SystemExit(_impl.main())
