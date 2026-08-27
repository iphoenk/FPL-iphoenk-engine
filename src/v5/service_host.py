from __future__ import annotations

import importlib
import os
from time import perf_counter
from typing import Any, Callable

import msgpack
from fastapi import FastAPI, HTTPException, Request, Response

from src.v5.config_cache import load_json_config
from src.v5.service_contracts import ServiceResponse
from src.v5.service_health import local_service_health
from src.v5.service_registry import get_service, registry

SERVICE_ID = os.getenv("V5_SERVICE_ID", "orchestrator").strip() or "orchestrator"
SPEC = get_service(SERVICE_ID)
REGISTRY = registry()
DEFAULTS = REGISTRY["defaults"]
WIRE_CONFIG = "config/v5_service_wire_registry.json"
WIRE = load_json_config(WIRE_CONFIG)


def _load_handler(path: str) -> Callable[[str, dict[str, Any]], Any]:
    module_name, function_name = path.split(":", 1)
    module = importlib.import_module(module_name)
    handler = getattr(module, function_name)
    if not callable(handler):
        raise RuntimeError(f"V5 service handler is not callable: {path}")
    return handler


def _wire_profile(codec: str) -> dict[str, Any]:
    profiles = WIRE.get("profiles") if isinstance(WIRE.get("profiles"), dict) else {}
    matches = [row for row in profiles.values() if isinstance(row, dict) and str(row.get("codec")) == codec]
    if len(matches) != 1:
        raise RuntimeError(f"V5 wire registry must define exactly one {codec} profile")
    return matches[0]


def _execute(operation: str, payload: dict[str, Any], correlation_id: str | None) -> dict[str, Any]:
    requested_contract = str(payload.pop("_contract_version", DEFAULTS["contract_version"]))
    active_contract = str(DEFAULTS["contract_version"])
    if requested_contract != active_contract:
        raise HTTPException(
            status_code=409,
            detail=f"contract mismatch requested={requested_contract} active={active_contract}",
        )
    started = perf_counter()
    try:
        data = HANDLER(operation, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        elapsed = round((perf_counter() - started) * 1000.0, 3)
        return ServiceResponse(
            service_id=SERVICE_ID,
            operation=operation,
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
            contract_version=active_contract,
            correlation_id=correlation_id,
            elapsed_ms=elapsed,
        ).as_dict()
    elapsed = round((perf_counter() - started) * 1000.0, 3)
    return ServiceResponse(
        service_id=SERVICE_ID,
        operation=operation,
        ok=True,
        data=data,
        contract_version=active_contract,
        correlation_id=correlation_id,
        elapsed_ms=elapsed,
    ).as_dict()


HANDLER = _load_handler(SPEC.handler)
app = FastAPI(title=f"FPL iphoenk V5 {SERVICE_ID} service", version=str(DEFAULTS["contract_version"]))
JSON_PROFILE = _wire_profile("json")
MSGPACK_PROFILE = _wire_profile("msgpack")


@app.get(str(DEFAULTS["health_path"]))
def health() -> dict[str, Any]:
    readiness = local_service_health(SERVICE_ID)
    return {
        **readiness,
        "contract_version": DEFAULTS["contract_version"],
    }


@app.get(str(DEFAULTS["meta_path"]))
def meta() -> dict[str, Any]:
    return {
        "service_id": SPEC.service_id,
        "bounded_context": SPEC.bounded_context,
        "owns_modules": list(SPEC.owns_modules),
        "dependencies": list(SPEC.dependencies),
        "critical": SPEC.critical,
        "status": SPEC.status,
        "port": SPEC.port,
        "contract_version": DEFAULTS["contract_version"],
        "wire_codecs": list(WIRE.get("allowed_codecs") or []),
    }


@app.post(str(JSON_PROFILE["invoke_path"]))
def invoke(operation: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(body or {})
    correlation_id = payload.pop("_correlation_id", None)
    return _execute(operation, payload, correlation_id)


@app.post(str(MSGPACK_PROFILE["invoke_path"]))
async def invoke_binary(operation: str, request: Request) -> Response:
    raw = await request.body()
    try:
        decoded = msgpack.unpackb(raw, raw=False, strict_map_key=False) if raw else {}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid msgpack payload: {type(exc).__name__}") from exc
    if not isinstance(decoded, dict):
        raise HTTPException(status_code=400, detail="msgpack request payload must be an object")
    payload = dict(decoded)
    correlation_id = payload.pop("_correlation_id", None)
    envelope = _execute(operation, payload, correlation_id)
    encoded = msgpack.packb(envelope, use_bin_type=True)
    return Response(content=encoded, media_type=str(MSGPACK_PROFILE["content_type"]))
