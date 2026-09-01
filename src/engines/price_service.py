from __future__ import annotations

import os
from pathlib import Path

from src.engines.price_calibration import capture_previous_state, patch_files as patch_price_calibration
from src.engines.price_challenger_overlay import patch_files as patch_challenger_context
from src.engines.price_mover_serving import patch_price_artifacts
from src.engines.price_radar import patch_files as patch_official_price_radar


def run(data_dir: str | Path | None = None) -> None:
    root = Path(data_dir or os.getenv("FPL_DATA_DIR") or "data")
    previous_price_state = capture_previous_state(root)
    patch_official_price_radar(root)
    patch_price_calibration(root, previous_price_state)
    patch_challenger_context(root)
    patch_price_artifacts(root)


if __name__ == "__main__":
    run()
