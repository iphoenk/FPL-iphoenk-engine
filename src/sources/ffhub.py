from __future__ import annotations
from src.sources.base import SourceResult, SourceSpec
from src.sources.public_web import probe_public_web

def probe(spec: SourceSpec, timeout_seconds: float = 2.5) -> SourceResult:
    return probe_public_web(spec, timeout_seconds)
