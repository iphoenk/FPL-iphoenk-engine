"""Bridge to the canonical acquisition-owned HTTP client."""
from ..acquisition import http_client as _impl

globals().update({name: getattr(_impl, name) for name in dir(_impl) if not name.startswith("__")})
