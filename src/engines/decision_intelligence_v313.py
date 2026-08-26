"""Compatibility entrypoint for historical imports.

The active V3 runtime service is version-neutral at ``src.engines.prediction_service``.
This module remains only to avoid breaking old imports and must not be referenced by
service registries or new production code.
"""

from __future__ import annotations

from src.engines.prediction_service import run


if __name__ == "__main__":
    run()
