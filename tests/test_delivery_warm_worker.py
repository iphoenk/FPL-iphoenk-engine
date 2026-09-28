from copy import deepcopy

import pytest

from src.engines.v12_p6_warm_worker import (
    CANONICAL_ENGINE_ONLY,
    CRON_AUTHORITY,
    SCHEDULER_AUTHORITY,
    CanonicalCallbacks,
    WarmIdentity,
    WarmWorker,
    WarmWorkerError,
    WorkerState,
)
from src.engines.v12_scenario_package import build_scenario_package


IDENTITY = WarmIdentity(
    production_sha="a" * 40,
    runtime_data_sha="b" * 40,
    model_version="V12",
    schema_version="6",
    gw_fixture_fingerprint="gw6",
    projection_lineage_fingerprint="proj",
    current15_fingerprint="our15",
    owner_context_fingerprint="owner-private",
    mc_authority="V12_MC_500K_CRN",
    runtime_class="NORMALIZED",
)


def result(action="WAIT"):
    return {
        "decision_surfaces": {
            "S06": {"xi": list(range(1, 12)), "bench": [12, 13, 14, 15]},
            "S08": {"captain": 1, "vice": 2},
            "S09": {"chip": "NONE"},
            "S14": {"route": "HOLD"},
            "S19": {"action": action},
        }
    }


def package():
    return build_scenario_package(
        dependencies=IDENTITY.p4_dependencies(),
        base_result=result(),
        owned_elements=list(range(1, 16)),
        evaluate=lambda override: result("PREPARE"),
        generated_at="2026-09-28T10:00:00+07:00",
        captain_element=1,
        vice_element=2,
    )


def callbacks(clock):
    def load(identity, private_state):
        return {
            "identity": dict(identity.__dict__),
            "semantic_surface": {"S19": "WAIT", "private": bool(private_state)},
        }

    def recompute(state, change, plan):
        new = deepcopy(state)
        new["semantic_surface"] = {"S19": "WAIT", "change": change["change_class"]}
        actual = dict(plan.expected)
        reused = {}
        return new, actual, reused

    def stage3(state):
        clock[0] += 0.5
        return {"status": "PASS"}

    def render(state, stage3):
        clock[0] += 0.5
        return {"semantic_surface": deepcopy(state["semantic_surface"])}

    def qa(rendered, stage3):
        clock[0] += 0.5
        return {"status": "PASS"}

    def publish(rendered, qa):
        clock[0] += 0.5
        return {"private_delivery_status": "PASS"}

    return CanonicalCallbacks(load, recompute, stage3, render, qa, publish)


def test_p6_has_no_scheduler_or_second_model_authority():
    assert SCHEDULER_AUTHORITY is False
    assert CRON_AUTHORITY is False
    assert CANONICAL_ENGINE_ONLY is True


def test_lifecycle_is_bounded_and_clean_shutdown():
    clock = [100.0]
    worker = WarmWorker(
        identity=IDENTITY,
        private_state={"current15": "PRIVATE"},
        scenario_package=package(),
        callbacks=callbacks(clock),
        ttl_seconds=60,
        clock=lambda: clock[0],
    )
    worker.start()
    assert worker.state == WorkerState.WARM_READY
    out = worker.apply_change({"change_class": "UNCHANGED", "scope_certain": True})
    assert out["private_delivery_status"] == "PASS"
    assert worker.state == WorkerState.WARM_READY
    worker.shutdown()
    assert worker.state == WorkerState.CLEAN_SHUTDOWN
    assert worker.canonical_state is None


def test_ttl_must_be_strictly_below_six_hours():
    with pytest.raises(WarmWorkerError, match="strictly below 6 hours"):
        WarmWorker(
            identity=IDENTITY,
            private_state={},
            scenario_package=package(),
            callbacks=callbacks([0.0]),
            ttl_seconds=6 * 60 * 60,
        )


def test_wrong_model_owner_or_stale_state_rejected():
    clock = [0.0]
    cb = callbacks(clock)
    original = cb.load_canonical_state
    cb.load_canonical_state = lambda identity, private: {
        **original(identity, private),
        "identity": {**dict(identity.__dict__), "model_version": "WRONG"},
    }
    worker = WarmWorker(
        identity=IDENTITY,
        private_state={},
        scenario_package=package(),
        callbacks=cb,
        clock=lambda: clock[0],
    )
    with pytest.raises(WarmWorkerError, match="wrong/stale"):
        worker.start()


def test_stale_p4_package_rejected():
    clock = [0.0]
    stale = package()
    stale["current_base_fingerprint"] = "wrong"
    worker = WarmWorker(
        identity=IDENTITY,
        private_state={},
        scenario_package=stale,
        callbacks=callbacks(clock),
        clock=lambda: clock[0],
    )
    with pytest.raises(WarmWorkerError, match="P4 package"):
        worker.start()


def test_unsupported_change_fails_closed():
    clock = [0.0]
    worker = WarmWorker(
        identity=IDENTITY,
        private_state={},
        scenario_package=package(),
        callbacks=callbacks(clock),
        clock=lambda: clock[0],
    )
    worker.start()
    with pytest.raises(WarmWorkerError, match="unsupported change fails closed"):
        worker.apply_change({"change_class": "UNKNOWN_CHANGE"})


def test_private_state_is_cleared_on_shutdown():
    clock = [0.0]
    worker = WarmWorker(
        identity=IDENTITY,
        private_state={"manager_specific": "secret"},
        scenario_package=package(),
        callbacks=callbacks(clock),
        clock=lambda: clock[0],
    )
    worker.start()
    worker.shutdown()
    assert worker._private_state == {}
