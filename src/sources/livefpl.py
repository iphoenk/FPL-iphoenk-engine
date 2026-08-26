from __future__ import annotations

from src.sources.base import SourceResult, SourceSpec
from src.sources.public_web import probe_public_web


def probe(spec: SourceSpec, timeout_seconds: float = 2.5) -> SourceResult:
    """Read-only public LiveFPL adapter.

    v1 intentionally performs reachability/capability discovery only. It does not
    scrape or invent price/EO/live-rank values. Structured ingestion can be added
    behind this adapter without changing downstream contracts.
    """
    return probe_public_web(spec, timeout_seconds)
