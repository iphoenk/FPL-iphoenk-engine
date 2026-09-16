"""Compatibility facade for canonical security utilities."""
from .domains.governance import security as _impl
import sys as _sys

globals().update({name: getattr(_impl, name) for name in dir(_impl) if not name.startswith("__")})
_sys.modules[__name__] = _impl
