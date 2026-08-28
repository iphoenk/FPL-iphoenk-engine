from __future__ import annotations

import csv
import io

import requests


def fetch_csv(url: str, timeout: int) -> list[dict]:
    """Fetch a CSV document over HTTP and return DictReader rows."""
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return list(csv.DictReader(io.StringIO(response.text)))
