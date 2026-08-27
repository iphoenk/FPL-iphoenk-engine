import pytest
from src.v5.intelligence.feature_bundle import FeatureBundle

def test_available_is_not_active_until_consumed():
    b=FeatureBundle(); b.declare("x",{"value":1}); snap=b.snapshot(); assert snap["states"]["x"]["state"]=="AVAILABLE"
    b.consume("x","prediction"); snap=b.snapshot(); assert snap["states"]["x"]["state"]=="ACTIVE"; assert snap["states"]["x"]["consumed_by"]==["prediction"]

def test_unavailable_never_fabricates_zero_evidence():
    b=FeatureBundle(); b.declare("missing",reason="not supplied"); snap=b.snapshot(); assert snap["states"]["missing"]["state"]=="UNAVAILABLE"; assert snap["states"]["missing"]["evidence"] is None
    with pytest.raises(KeyError): b.consume("missing","prediction")
