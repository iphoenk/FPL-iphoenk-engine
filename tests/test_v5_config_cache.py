from src.v5.config_cache import clear_config_cache, load_json_config


def test_shared_config_loader_caches_reads():
    clear_config_cache()
    a = load_json_config("config/v5_performance_budgets.json")
    b = load_json_config("config/v5_performance_budgets.json")
    assert a is b
    info = load_json_config.cache_info()
    assert info.hits >= 1
