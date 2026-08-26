from __future__ import annotations

import os
from pathlib import Path

from src.engines.price_challenger_overlay import patch_files as patch_challenger_context
from src.engines.price_radar import patch_files as patch_official_price_radar


def run(data_dir: str | Path | None = None) -> None:
    root = Path(data_dir or os.getenv("FPL_DATA_DIR") or "data")
    patch_official_price_radar(root)
    patch_challenger_context(root)


if __name__ == "__main__":
    run()
