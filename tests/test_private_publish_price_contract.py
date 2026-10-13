from __future__ import annotations

import pytest

from src.engines.v12_private_publisher import PrivatePublishError, validate_price_publish_classification


def test_private_publisher_rejects_unclassified_degraded_price():
    with pytest.raises(PrivatePublishError, match="PRICE_DEGRADED_CLASSIFICATION_INVALID"):
        validate_price_publish_classification(
            {
                "report_mode": "PRICE",
                "runner_status": "PARTIAL",
                "delivery_status": "READY_DEGRADED",
                "price_execution_mode": "PUBLIC_FIRST_DEGRADED",
            }
        )


def test_private_publisher_accepts_explicit_public_first_degraded_price():
    result = validate_price_publish_classification(
        {
            "report_mode": "PRICE",
            "runner_status": "PARTIAL",
            "delivery_status": "READY_DEGRADED_PUBLIC_FIRST",
            "price_execution_mode": "PUBLIC_FIRST_DEGRADED",
            "personal_finance_status": "UNAVAILABLE",
            "personal_data_fabricated": False,
            "section_count": 12,
            "qa_status": "PASS",
        }
    )
    assert result["status"] == "PASS"

