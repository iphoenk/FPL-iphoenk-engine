from __future__ import annotations

from src.engines.price_mover_serving import patch_price_artifacts
from src.services.prediction_service import run as run_prediction
from src.utils import DATA


def run():
    result = run_prediction()
    patch_price_artifacts(DATA)
    return result


if __name__ == "__main__":
    run()
