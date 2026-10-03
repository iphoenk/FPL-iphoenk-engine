from __future__ import annotations

import json
from contextlib import AbstractContextManager
from pathlib import Path

from src.engines.report_time_web_capture import build_targets
from src.sources.camoufox_transport import CaptureTarget, capture_targets
from src.utils import ROOT


class _FakeResponse:
    status = 200


class _FakeLocator:
    def __init__(self, text: str):
        self.text = text

    def inner_text(self, timeout: int = 0) -> str:
        return self.text


class _FakePage:
    def __init__(self, text: str, *, final_url: str = "https://example.com/news"):
        self._text = text
        self.url = final_url
        self.closed = False

    def set_default_navigation_timeout(self, timeout: int) -> None:
        self.timeout = timeout

    def goto(self, url: str, wait_until: str, timeout: int):
        self.requested_url = url
        return _FakeResponse()

    def wait_for_timeout(self, timeout: int) -> None:
        self.waited = timeout

    def title(self) -> str:
        return "Public team news"

    def locator(self, selector: str) -> _FakeLocator:
        assert selector == "body"
        return _FakeLocator(self._text)

    def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self, text: str):
        self.text = text

    def new_page(self) -> _FakePage:
        return _FakePage(self.text)


class _FakeManager(AbstractContextManager):
    def __init__(self, text: str):
        self.browser = _FakeBrowser(text)

    def __enter__(self):
        return self.browser

    def __exit__(self, exc_type, exc, tb):
        return False


def _factory(text: str):
    return lambda: _FakeManager(text)


def test_camoufox_public_source_policy_is_bounded_to_information_acquisition():
    config = json.loads(
        (ROOT / "config" / "sources" / "camoufox_public_sources.json").read_text(
            encoding="utf-8"
        )
    )
    policy = config["policy"]
    assert config["contract"] == "CAMOUFOX_PUBLIC_INFORMATION_ACQUISITION_V1"
    assert policy["transport"] == "CAMOUFOX"
    assert policy["public_read_only"] is True
    assert policy["authentication_forbidden"] is True
    assert policy["member_or_paywalled_pages_forbidden"] is True
    assert policy["captcha_solving_forbidden"] is True
    assert policy["official_fpl_api_remains_direct"] is True
    assert policy["structured_api_and_csv_sources_remain_direct"] is True
    assert policy["raw_capture_never_mutates_dss_or_model"] is True
    assert (
        policy[
            "raw_capture_never_becomes_verified_fact_without_existing_evidence_validation"
        ]
        is True
    )
    assert policy["source_failure_is_non_blocking"] is True

    source_ids = {row["source_id"] for row in config["sources"] if row["enabled"]}
    assert "official_fpl" not in source_ids
    assert {
        "ffscout_editorial",
        "rotowire",
        "premier_league_official_news",
        "onefpl",
        "fffix",
        "ffhub",
    }.issubset(source_ids)

    for row in config["sources"]:
        for url in row.get("urls") or []:
            assert url.startswith("https://")
            assert "/members" not in url.casefold()


def test_camoufox_dependency_is_exact_stable_pin():
    requirement = (
        ROOT / "requirements-report-web.txt"
    ).read_text(encoding="utf-8")
    assert "camoufox==0.5.6" in requirement
    assert "0.5.7b" not in requirement


def test_capture_is_raw_provenance_not_semantic_or_fact_promotion():
    result = capture_targets(
        [
            CaptureTarget(
                source_id="ffscout_editorial",
                source_class="PUNDIT_CONSENSUS",
                url="https://example.com/news",
                purpose=("team_news",),
            )
        ],
        settle_milliseconds=0,
        browser_factory=_factory("Player availability update"),
    )
    assert result["status"] == "READY"
    assert result["transport"] == "CAMOUFOX"
    assert result["available_count"] == 1
    row = result["captures"][0]
    assert row["status"] == "AVAILABLE"
    assert row["visible_text"] == "Player availability update"
    assert row["semantic_inference_performed"] is False
    assert row["fact_promotion_performed"] is False
    assert result["policy"]["source_failure_is_non_blocking"] is True


def test_access_challenge_is_not_retained_as_information():
    result = capture_targets(
        [
            CaptureTarget(
                source_id="example",
                source_class="REFERENCE",
                url="https://example.com/news",
            )
        ],
        settle_milliseconds=0,
        browser_factory=_factory("Just a moment... verify that you're not a robot"),
    )
    row = result["captures"][0]
    assert row["status"] == "ACCESS_RESTRICTED"
    assert row["visible_text"] == ""
    assert row["fact_promotion_performed"] is False


def test_report_time_targets_are_deduplicated_and_registry_driven():
    config = {
        "sources": [
            {
                "source_id": "a",
                "source_class": "NEWS",
                "enabled": True,
                "purpose": ["team_news"],
                "urls": [
                    "https://example.com/a",
                    "https://example.com/a",
                ],
            },
            {
                "source_id": "disabled",
                "source_class": "NEWS",
                "enabled": False,
                "urls": ["https://example.com/b"],
            },
        ]
    }
    targets = build_targets(config)
    assert len(targets) == 1
    assert targets[0].source_id == "a"
    assert targets[0].purpose == ("team_news",)


def test_v12_workflow_keeps_camoufox_optional_and_out_of_price_lane():
    workflow = (
        ROOT / ".github" / "workflows" / "v12-integrated-report-runner.yml"
    ).read_text(encoding="utf-8")
    assert "Cache Camoufox browser" in workflow
    assert "Install Camoufox report-time transport" in workflow
    assert "Capture report-time public information with Camoufox" in workflow
    assert "requirements-report-web.txt" in workflow
    assert "python -m camoufox fetch" in workflow
    assert "report_time_web_capture.json" in workflow
    assert "needs.parse.outputs.report_mode != 'PRICE'" in workflow
