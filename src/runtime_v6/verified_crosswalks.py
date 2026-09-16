"""Compatibility facade for the canonical verified-crosswalks implementation."""
from .domains.identity import verified_crosswalks as _impl

globals().update({name: getattr(_impl, name) for name in dir(_impl) if not name.startswith("__")})

if __name__ == "__main__" and hasattr(_impl, "main"):
    raise SystemExit(_impl.main())
