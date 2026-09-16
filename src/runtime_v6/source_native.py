"""Compatibility module alias for canonical source-native normalizer."""
from .domains.acquisition import source_native as _impl
import sys as _sys

globals().update({name: getattr(_impl, name) for name in dir(_impl) if not name.startswith("__")})
_sys.modules[__name__] = _impl
