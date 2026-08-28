import pytest

from src.v5.intelligence.feature_bundle import FeatureBundle


def test_available_is_not_active_until_consumed():
    b = FeatureBundle()
    b.declare("x", {"value": 1})
    snap = b.snapshot()
    assert snap["schema_version"] == 2
    assert snap["states"]["x"]["state"] == "AVAILABLE"
    assert snap["states"]["x"]["authoritative_effect"] is False
    assert snap["states"]["x"]["effect_scopes"] == []

    b.consume("x", "prediction")
    snap = b.snapshot()
    assert snap["states"]["x"]["state"] == "ACTIVE"
    assert snap["states"]["x"]["consumed_by"] == ["prediction"]
    assert snap["states"]["x"]["effect_scopes"] == ["OBSERVABILITY_ONLY"]
    assert snap["states"]["x"]["authoritative_effect"] is False


def test_shadow_consumption_is_active_but_not_authoritative():
    b = FeatureBundle()
    b.declare("rest", {"days": 3})
    b.consume("rest", "advanced_prediction", effect_scope="SHADOW_OVERLAY")
    row = b.snapshot()["states"]["rest"]
    assert row["state"] == "ACTIVE"
    assert row["effect_scopes"] == ["SHADOW_OVERLAY"]
    assert row["authoritative_effect"] is False
    assert row["consumption_evidence"][0]["authoritative_effect"] is False


def test_authoritative_xpts_consumption_requires_explicit_scope():
    b = FeatureBundle()
    b.declare("team_strength", {"attack": 1.1})
    b.consume(
        "team_strength",
        "native_projection",
        effect_scope="AUTHORITATIVE_XPTS",
        contribution={"attack_multiplier": 1.1},
    )
    snap = b.snapshot()
    row = snap["states"]["team_strength"]
    assert row["authoritative_effect"] is True
    assert row["effect_scopes"] == ["AUTHORITATIVE_XPTS"]
    assert row["consumption_evidence"][0]["contribution"] == {"attack_multiplier": 1.1}
    assert snap["authoritative_active_count"] == 1


def test_same_feature_can_have_multiple_explicit_effect_scopes():
    b = FeatureBundle()
    b.declare("role", {"starter": 0.9})
    b.consume("role", "native_projection", effect_scope="AUTHORITATIVE_XMINS")
    b.consume("role", "native_projection", effect_scope="AUTHORITATIVE_XPTS")
    row = b.snapshot()["states"]["role"]
    assert row["consumed_by"] == ["native_projection"]
    assert row["effect_scopes"] == ["AUTHORITATIVE_XMINS", "AUTHORITATIVE_XPTS"]
    assert row["authoritative_effect"] is True
    assert len(row["consumption_evidence"]) == 2


def test_unavailable_never_fabricates_zero_evidence():
    b = FeatureBundle()
    b.declare("missing", reason="not supplied")
    snap = b.snapshot()
    assert snap["states"]["missing"]["state"] == "UNAVAILABLE"
    assert snap["states"]["missing"]["evidence"] is None
    assert snap["states"]["missing"]["authoritative_effect"] is False
    with pytest.raises(KeyError):
        b.consume("missing", "prediction")


def test_invalid_effect_scope_is_rejected():
    b = FeatureBundle()
    b.declare("x", {"value": 1})
    with pytest.raises(ValueError, match="invalid feature effect scope"):
        b.consume("x", "prediction", effect_scope="MAGIC")
