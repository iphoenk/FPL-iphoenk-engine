"""Canonical entrypoint for the V3 package optimizer representation-only frontier contract.

Implementation remains runtime-evidence aware while this engine-level entrypoint keeps
package-optimizer ownership explicit and makes sharded acceptance path-sensitive.
"""

from src.runtime_v3.frontier_evidence_contract import install

__all__ = ["install"]
