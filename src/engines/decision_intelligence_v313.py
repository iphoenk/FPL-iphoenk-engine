from __future__ import annotations

import json
from datetime import datetime, timezone

from src.engines.decision_intelligence import build_package_optimizer
from src.models.historical_projection import build as build_player_projections
from src.models.prediction_quality import evaluate as evaluate_prediction_quality
from src.models.team_strength import build_team_strength
from src.sources.official_fpl import get_json
from src.utils import DATA, atomic_json, read_json


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run():
    bootstrap, bh = get_json("bootstrap-static/")
    fixtures, fh = get_json("fixtures/")
    if not bootstrap or not fixtures:
        raise RuntimeError(f"Official FPL unavailable: bootstrap={bh.get('status')} fixtures={fh.get('status')}")
    prior = read_json(DATA / "prior_season.json", {})
    if not prior.get("players"):
        raise RuntimeError("historical prior artifact unavailable for v3.13 prediction")

    latest = read_json(DATA / "latest.json", {})
    planning_gw = int((latest.get("phase") or {}).get("planning_gw") or 1)
    strength = build_team_strength(bootstrap, fixtures)
    strength["generated_at"] = _now()
    strength["source_health"] = {"bootstrap": bh.get("status"), "fixtures": fh.get("status")}
    atomic_json(DATA / "team_strength.json", strength)

    projections = build_player_projections(bootstrap, strength, planning_gw, prior, horizon=15)
    projections["generated_at"] = _now()
    atomic_json(DATA / "projections.json", projections)
    packages = build_package_optimizer(projections, read_json(DATA / "team.json", {}))
    atomic_json(DATA / "package_optimizer.json", packages)
    quality = evaluate_prediction_quality(projections, prior)
    atomic_json(DATA / "prediction_quality.json", quality)

    latest.setdefault("files", {}).update({
        "team_strength": "data/team_strength.json", "projections": "data/projections.json",
        "package_optimizer": "data/package_optimizer.json", "prediction_quality": "data/prediction_quality.json"
    })
    latest["decision_intelligence"] = {
        "model": projections.get("model"), "planning_gw": planning_gw,
        "projection_players": len(projections.get("players") or []),
        "team_strength_model": strength.get("model"), "team_strength_teams": len(strength.get("teams") or []),
        "historical_prior_model": projections.get("historical_prior_model"),
        "historical_prior_players_used": projections.get("historical_prior_players_used"),
        "prediction_quality": quality.get("status"), "package_optimizer_status": packages.get("status"),
        "package_count": packages.get("package_count", 0),
        "best_package": (packages.get("packages") or [{}])[0].get("id") if packages.get("packages") else None,
        "candidate_generation_only": True
    }
    latest["prediction_quality_summary"] = {
        "status": quality.get("status"), "failed_checks": quality.get("failed_checks"), "checks": quality.get("checks")
    }
    atomic_json(DATA / "latest.json", latest)
    return {"strength": strength, "projections": projections, "packages": packages, "quality": quality}


if __name__ == "__main__":
    out = run()
    print(json.dumps({
        "projection_players": len(out["projections"].get("players") or []),
        "historical_prior_players": out["projections"].get("historical_prior_players_used"),
        "prediction_quality": out["quality"].get("status"),
        "package_count": out["packages"].get("package_count"),
        "best_package": (out["packages"].get("packages") or [{}])[0].get("id") if out["packages"].get("packages") else None
    }, ensure_ascii=False))
