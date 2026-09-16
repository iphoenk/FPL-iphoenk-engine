"""Compatibility module alias for canonical Official FPL client."""
from .domains.acquisition import official_fpl_client as _impl
import sys as _sys

globals().update({name: getattr(_impl, name) for name in dir(_impl) if not name.startswith("__")})
_sys.modules[__name__] = _impl
