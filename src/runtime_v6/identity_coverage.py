"""Compatibility facade for the canonical identity-coverage implementation."""
from .domains.identity import identity_coverage as _impl

globals().update({name: getattr(_impl, name) for name in dir(_impl) if not name.startswith("__")})

if __name__ == "__main__" and hasattr(_impl, "main"):
    raise SystemExit(_impl.main())
