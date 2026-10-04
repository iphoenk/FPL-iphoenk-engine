from src.engines.v12_report_orchestration import _render_package_frontier_lines
from src.runtime_v6.domains.report_plane.report_qa import _required_visible_markers



def test_serialized_mapping_strings_are_humanized():
    from src.engines.v12_report_orchestration import _human_summary

    assert _human_summary("{'classification': 'FRAGILE'}") == "classification=FRAGILE"
