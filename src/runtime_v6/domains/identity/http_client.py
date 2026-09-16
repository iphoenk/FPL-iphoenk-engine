"""Temporary bridge to the acquisition-owned HTTP client during Wave 13 migration."""
from ... import http_client as _impl

globals().update({name: getattr(_impl, name) for name in dir(_impl) if not name.startswith("__")})
