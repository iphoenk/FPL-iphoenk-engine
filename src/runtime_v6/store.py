"""Compatibility module alias for the canonical publication store."""
from .domains.publication import store as _impl
import sys as _sys

_sys.modules[__name__] = _impl
