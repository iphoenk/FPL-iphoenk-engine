"""Temporary bridge to the publication-owned store during Wave 13 migration."""
from ... import store as _impl

globals().update({name: getattr(_impl, name) for name in dir(_impl) if not name.startswith("__")})
