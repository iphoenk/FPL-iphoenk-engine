"""Bridge to the canonical control-plane runtime control."""
from ..control_plane import runtime_control as _impl

globals().update({name: getattr(_impl, name) for name in dir(_impl) if not name.startswith("__")})
