from src.runtime_v3 import domain_orchestrator as runtime


def test_model_market_are_only_parallel_isolated_domains():
    assert runtime._PARALLEL_ISOLATED_DOMAINS == ("MODEL", "MARKET")
    registry = runtime._load_domains()
    policy = registry["policy"]
    assert policy["model_and_market_use_isolated_workspaces"] is True
    assert policy["model_and_market_may_execute_in_parallel"] is True
    assert policy["parallel_domain_fan_in_uses_declared_artifacts_and_latest_keys_only"] is True
    assert policy["parallel_domain_fan_in_is_deterministic"] is True


def test_seed_paths_are_contract_derived():
    services = {
        "a": {"inputs": ["in/a.json"], "artifacts": ["out/a.json"]},
        "b": {"inputs": ["in/b.json"], "artifacts": ["out/b.json"]},
    }
    assert runtime._domain_seed_paths(["a", "b"], services) == [
        "in/a.json",
        "in/b.json",
        "incremental_reuse_state.json",
        "latest.json",
        "out/a.json",
        "out/b.json",
    ]


def test_model_market_declared_latest_write_sets_do_not_overlap():
    services = runtime.legacy._load_registry()["services"]
    domains = runtime._load_domains()["domains"]

    def write_set(domain_name: str) -> tuple[set[str], set[str], set[str]]:
        artifacts: set[str] = set()
        latest_keys: set[str] = set()
        latest_file_keys: set[str] = set()
        for capability in domains[domain_name]["capabilities"]:
            spec = services[capability]
            artifacts.update(str(x) for x in spec.get("artifacts") or [])
            latest_keys.update(str(x) for x in spec.get("latest_keys") or [])
            latest_file_keys.update(str(x) for x in spec.get("latest_file_keys") or [])
        return artifacts, latest_keys, latest_file_keys

    model = write_set("MODEL")
    market = write_set("MARKET")
    assert model[0].isdisjoint(market[0])
    assert model[1].isdisjoint(market[1])
    assert model[2].isdisjoint(market[2])
