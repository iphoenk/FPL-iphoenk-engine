# V5 Microservices Architecture

V5 is required to run as bounded-context microservices. The repository may remain a monorepo and services may share one immutable container image, but the production runtime must not collapse back into one process.

## Why bounded contexts, not per-function services

The engine contains many small pure functions. Turning each into a network service would add serialization, network latency, failure modes, and operational noise. V5 therefore keeps fine-grained modules and registries internally, while deploying larger business boundaries as independent services.

## Service topology

```text
                        orchestrator :8100
                               |
                               v
                        ingestion :8101
                         /          \
                        v            v
                  truth :8102     authenticated/public data
                    |  \
                    |   \
                    v    v
             price :8103  prediction :8104
                    \       /
                     \     /
                      v   v
                    decision :8105
                         |
                         v
                    snapshot :8106
```

The exact topology, ports, ownership, dependencies, contract version, criticality, and timeout defaults are controlled by `config/v5_service_registry.json`.

## Boundaries

### ingestion
Owns Official public collection, authenticated read-only collection, and source authority. It never persists credentials or raw authentication material.

### truth
Owns Official rules, phase context, element identity, squad authority, finance authority, team-state assembly, and personalized live scoring. This service is the canonical answer to “what is true about the user's team right now?”.

### price
Owns price trajectory, urgency, ETA, price alerts, and price-market overlays. Thresholds and limits remain registry driven.

### prediction
Owns projection and the V4-to-V5 prediction bridge during convergence. The bridge is temporary; V5 must eventually own the full production prediction contract.

### decision
Owns Gate0, DSS core/extensions, optimizer governance, and Evidence → Prediction → Decision trace. During alpha it may bridge legacy V4 decision components, but it must not claim a production recommendation until migrated and accepted.

### snapshot
Owns V5 persistence and history. V5 artifacts remain isolated under `data/v5/` and raw authenticated payload persistence remains prohibited.

### orchestrator
Owns workflow orchestration and observability only. It must not contain business rules. Independent calls are fanned out in parallel where possible.

## Service contract

Every service exposes:

- `GET /health`
- `GET /meta`
- `POST /v1/invoke/{operation}`

Requests and responses use versioned contracts and correlation IDs. The shared service host loads the service handler from the service registry, so service IDs and business handlers are not hardcoded into the host.

## Ownership rule

Every registered V5 module must have exactly one service owner. Duplicate ownership and unowned modules fail the V5 acceptance gate. This prevents rules, finance, phase authority, or other business semantics from diverging between services.

## Performance rules

Microservices do not relax V5 performance requirements:

1. independent calls should execute concurrently;
2. identical Official endpoint reads are deduplicated;
3. immutable configs/registries are cached per process;
4. large transforms remain single-pass where possible;
5. avoid chatty request graphs and repeated serialization;
6. service latency must be measured separately from compute latency;
7. service boundaries may be regrouped only through the service registry and acceptance process, never through duplicated logic.

## Local stack

`deploy/v5/docker-compose.yml` runs the seven V5 services as separate containers using the shared `deploy/v5/Dockerfile` image. The orchestrator reaches other services by service DNS names and registry-aligned ports.

V3 production tasks remain independent of this stack while V5 is in alpha.
