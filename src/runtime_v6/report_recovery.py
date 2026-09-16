"""Compatibility facade for canonical report recovery."""
from .domains.report_plane import report_recovery as _impl
import sys as _sys

globals().update({name: getattr(_impl, name) for name in dir(_impl) if not name.startswith("__")})
if __name__ == "__main__" and hasattr(_impl, "main"):
    raise SystemExit(_impl.main())
_sys.modules[__name__] = _impl
