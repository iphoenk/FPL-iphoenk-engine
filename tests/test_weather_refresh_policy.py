from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from src.sources.weather_open_meteo import _observation_is_fresh

ROOT = Path(__file__).resolve().parents[1]


def _cfg():
    return json.loads((ROOT / "config/intelligence/weather_context.json").read_text(encoding="utf-8"))


def test_weather_parallelism_is_bounded():
    cfg = _cfg()
    workers = int(cfg["api"]["max_parallel_requests"])
    assert 1 <= workers <= 4


def test_near_kickoff_weather_uses_high_confidence_freshness_window():
    cfg = _cfg()
    now = datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc)
    kickoff = now + timedelta(hours=12)
    recent = {
        "fetched_at": (now - timedelta(hours=5)).isoformat(),
        "forecast_for": kickoff.isoformat(),
    }
    stale = {
        "fetched_at": (now - timedelta(hours=7)).isoformat(),
        "forecast_for": kickoff.isoformat(),
    }
    assert _observation_is_fresh(recent, kickoff, now, cfg) is True
    assert _observation_is_fresh(stale, kickoff, now, cfg) is False


def test_far_horizon_weather_can_reuse_longer_without_network_churn():
    cfg = _cfg()
    now = datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc)
    kickoff = now + timedelta(days=5)
    observation = {
        "fetched_at": (now - timedelta(hours=48)).isoformat(),
        "forecast_for": kickoff.isoformat(),
    }
    assert _observation_is_fresh(observation, kickoff, now, cfg) is True


def test_weather_reuse_rejects_observation_for_different_kickoff():
    cfg = _cfg()
    now = datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc)
    kickoff = now + timedelta(days=1)
    observation = {
        "fetched_at": now.isoformat(),
        "forecast_for": (kickoff + timedelta(hours=1)).isoformat(),
    }
    assert _observation_is_fresh(observation, kickoff, now, cfg) is False
