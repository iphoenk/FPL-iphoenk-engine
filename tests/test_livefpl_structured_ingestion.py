from __future__ import annotations

from src.sources.base import SourceSpec
from src.sources.livefpl import PARSER_VERSION, parse_price_observations, probe
from src.sources.structured_web import FetchedDocument


TABLE_HTML = """
<html><body>
<table>
  <tr><th>Player</th><th>Team</th><th>Progress Now</th><th>Prediction</th><th>Progress per hr</th><th>ID</th></tr>
  <tr>
    <td><strong>Raya</strong><br>GK £6.0 Raya</td>
    <td>Arsenal</td><td>9.9%</td><td>10.2% &gt;2 days</td><td>+0.18%</td><td>1</td>
  </tr>
  <tr>
    <td>De Cuyper<br>DEF £4.6 De Cuyper</td>
    <td>Brighton</td><td>28.7%</td><td>38.6% Tomorrow</td><td>+5.98%</td><td>115</td>
  </tr>
  <tr>
    <td>F.Kadıoğlu<br>DEF £4.5 F.Kadıoğlu</td>
    <td>Brighton</td><td>-109.2%</td><td>-110.0% Tonight</td><td>-0.48%</td><td>113</td>
  </tr>
</table>
</body></html>
"""


def _spec() -> SourceSpec:
    return SourceSpec(
        source_id="livefpl",
        name="LiveFPL",
        source_class="CHALLENGER",
        tier=2,
        enabled=True,
        critical=False,
        adapter="livefpl",
        capabilities=("price_prediction", "effective_ownership"),
        config={
            "structured_urls": ["https://primary.invalid/prices", "https://fallback.invalid/prices"],
            "probe_url": "https://probe.invalid/",
            "observation_ttl_seconds": 1800,
            "max_fetch_bytes": 1048576,
        },
    )


def test_table_parser_handles_current_livefpl_row_shape_without_cross_row_matching():
    rows = parse_price_observations(
        TABLE_HTML,
        source_url="https://www2.livefpl.net/prices",
        fetched_at="2026-08-31T04:00:00+00:00",
        ttl_seconds=1800,
    )
    assert len(rows) == 3
    by_name = {row["subject"]["player"]: row for row in rows}

    raya = by_name["Raya"]
    assert raya["parser_version"] == PARSER_VERSION
    assert raya["value"]["position"] == "GK"
    assert raya["value"]["price"] == 6.0
    assert raya["value"]["progress_pct"] == 9.9
    assert raya["value"]["predicted_pct"] == 10.2
    assert raya["value"]["per_hour_pct"] == 0.18
    assert raya["value"]["eta_label"] == ">2 days"

    de_cuyper = by_name["De Cuyper"]
    assert de_cuyper["value"]["direction"] == "RISE"
    assert de_cuyper["value"]["eta_label"] == "Tomorrow"

    kadioglu = by_name["F.Kadıoğlu"]
    assert kadioglu["value"]["direction"] == "FALL"
    assert kadioglu["value"]["eta_label"] == "Tonight"


def test_legacy_linear_text_parser_remains_supported():
    html = "<div>Example Player MID £7.5 98.0% 101.5% Tonight +2.1%</div>"
    rows = parse_price_observations(
        html,
        source_url="https://legacy.invalid/prices",
        fetched_at="2026-08-31T04:00:00+00:00",
        ttl_seconds=1800,
    )
    assert len(rows) == 1
    assert rows[0]["subject"]["player"] == "Example Player"
    assert rows[0]["value"]["predicted_pct"] == 101.5
    assert rows[0]["value"]["direction"] == "RISE"


def test_probe_uses_registry_order_and_falls_back_only_when_needed(monkeypatch):
    calls: list[str] = []

    def fake_fetch(url: str, timeout_seconds: float, *, max_bytes: int, user_agent: str = "") -> FetchedDocument:
        calls.append(url)
        if url == "https://primary.invalid/prices":
            return FetchedDocument(url, 502, "text/html", "", False, 12.0, "HTTPError")
        if url == "https://fallback.invalid/prices":
            return FetchedDocument(url, 200, "text/html", TABLE_HTML, True, 20.0, None)
        raise AssertionError(f"unexpected probe call: {url}")

    monkeypatch.setattr("src.sources.livefpl.fetch_public_document", fake_fetch)
    result = probe(_spec(), timeout_seconds=1.0)

    assert calls == ["https://primary.invalid/prices", "https://fallback.invalid/prices"]
    assert result.status == "LIVE"
    assert result.reachable is True
    assert result.observation_count == 3
    assert result.capabilities["price_prediction"] == "AVAILABLE"
    assert result.capabilities["effective_ownership"] == "SOURCE_REACHABLE_NO_STRUCTURED_OBSERVATION"
    assert result.detail["selected_url"] == "https://fallback.invalid/prices"
    assert len(result.detail["attempted_urls"]) == 2
    assert result.detail["data_values_ingested"] is True


def test_probe_does_not_fabricate_when_all_reachable_pages_have_no_rows(monkeypatch):
    calls: list[str] = []

    def fake_fetch(url: str, timeout_seconds: float, *, max_bytes: int, user_agent: str = "") -> FetchedDocument:
        calls.append(url)
        return FetchedDocument(url, 200, "text/html", "<html><body>shell only</body></html>", True, 5.0, None)

    monkeypatch.setattr("src.sources.livefpl.fetch_public_document", fake_fetch)
    result = probe(_spec(), timeout_seconds=1.0)

    assert calls == [
        "https://primary.invalid/prices",
        "https://fallback.invalid/prices",
        "https://probe.invalid/",
    ]
    assert result.status == "LIVE"
    assert result.reachable is True
    assert result.observation_count == 0
    assert result.capabilities["price_prediction"] == "SOURCE_REACHABLE_NO_STRUCTURED_OBSERVATION"
    assert result.detail["data_values_ingested"] is False
    assert result.detail["no_fabrication"] is True
