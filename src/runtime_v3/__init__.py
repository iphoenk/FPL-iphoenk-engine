"""V3 production bounded-process microservice runtime."""

RUNTIME_ID = "v3-bounded-process-microservices-v1"

# The sharded production optimizer reuses the canonical exhaustive scorer/search
# and extends only its representation-only Pareto frontier with governed evidence.
# This installation does not mutate xPts/xMins, legality, candidate generation,
# search width, package scoring, or decision authority.
from src.runtime_v3.frontier_evidence_contract import install as _install_frontier_evidence_contract

_install_frontier_evidence_contract()
del _install_frontier_evidence_contract
