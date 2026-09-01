from __future__ import annotations

from src.engines.price_mover_serving import patch_price_artifacts
from src.services.prediction_service import run as run_prediction
from src.utils import DATA


def run(*, return_predictions: bool = False):
    result = run_prediction(return_predictions=True) if return_predictions else run_prediction()
    patch_price_artifacts(DATA)
    return result


if __name__ == "__main__":
    run()
