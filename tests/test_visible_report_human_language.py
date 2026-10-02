from src.engines.v12_report_orchestration import _human_value, validate_human_facing_body
from src.engines.v12_price_delivery import _cell


def test_deep_machine_enums_are_translated_for_visible_report():
    assert _human_value("NO_POSITIVE_MC_SUPPORTED_ROUTE_CLEARS_1_3_5GW_VECTOR").startswith(
        "Belum ada rute transfer"
    )
    assert _human_value("PERSONAL_AUTH_UNAVAILABLE") == "Akses data personal belum tersedia"
    assert _human_value("COVARIANCE_NOT_MODELLED_YET") == "Korelasi antarpemain belum dimodelkan"


def test_human_facing_qa_rejects_raw_machine_enum_and_python_object():
    assert "MACHINE_LANGUAGE=RAW_INTERNAL_ENUM" in validate_human_facing_body(
        "Decision: NO_POSITIVE_MC_SUPPORTED_ROUTE_CLEARS_1_3_5GW_VECTOR"
    )
    assert "MACHINE_LANGUAGE=RAW_PYTHON_OR_JSON_OBJECT" in validate_human_facing_body(
        "user_summary: {'rank': 7, 'total': 344}"
    )


def test_price_cells_do_not_dump_python_dict_or_internal_ids():
    rendered = _cell({"entry_id": 3462711, "rank": 7, "total": 344})
    assert "entry_id" not in rendered
    assert "{" not in rendered
    assert "rank=7" in rendered
    assert "total=344" in rendered
