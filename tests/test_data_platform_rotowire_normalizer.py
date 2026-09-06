from __future__ import annotations

from src.runtime_v6.rotowire_normalizer import parse_rotowire_lineups


HTML = """
<div class="lineup is-soccer" data-gameid="98765">
  <div class="lineup__time"><b>September 12</b> 10:00 AM</div>
  <div class="lineup__mteam is-home">
    <a title="Everton"><div class="lineup__abbr">EVE</div> Everton</a>
  </div>
  <div class="lineup__mteam is-visit">
    <a title="Aston Villa"><div class="lineup__abbr">AVL</div> Aston Villa</a>
  </div>
  <ul class="lineup__list is-home">
    <li class="lineup__status is-confirmed">Confirmed Lineup</li>
    <li class="lineup__player">
      <div class="lineup__pos">GK</div>
      <a title="Jordan Pickford" href="/soccer/player/jordan-pickford-19035">Pickford</a>
    </li>
    <li class="lineup__title is-middle">Injuries</li>
    <li class="lineup__player">
      <div class="lineup__pos">F</div>
      <a title="Example Injured" href="/soccer/player/example-injured-99999">Example</a>
      <span class="lineup__inj">QUES</span>
    </li>
  </ul>
  <ul class="lineup__list is-visit">
    <li class="lineup__status is-expected">Predicted Lineup</li>
    <li class="lineup__player">
      <div class="lineup__pos">M</div>
      <a title="Example Villa" href="/soccer/player/example-villa-88888">Villa</a>
    </li>
  </ul>
</div>
"""


def test_rotowire_lineups_preserve_provider_semantics_and_native_ids():
    parsed = parse_rotowire_lineups(HTML)

    assert len(parsed["fixtures"]) == 1
    fixture = parsed["fixtures"][0]
    assert fixture["source_native_id"] == 98765
    assert fixture["home"] == {"name": "Everton", "abbr": "EVE"}
    assert fixture["away"] == {"name": "Aston Villa", "abbr": "AVL"}
    assert fixture["lineup_status"] == {"home": "CONFIRMED", "away": "PREDICTED"}

    assert len(parsed["lineups"]) == 2
    pickford = next(row for row in parsed["lineups"] if row["source_native_id"] == 19035)
    villa = next(row for row in parsed["lineups"] if row["source_native_id"] == 88888)
    assert pickford["record_semantic_class"] == "NORMALIZED_FACT"
    assert villa["record_semantic_class"] == "UPSTREAM_MODEL_SIGNAL"
    assert pickford["official_element_id"] is None
    assert pickford["identity_status"] == "UNMAPPED"

    assert len(parsed["availability"]) == 1
    injured = parsed["availability"][0]
    assert injured["source_native_id"] == 99999
    assert injured["availability_status"] == "QUES"
    assert injured["record_semantic_class"] == "SECONDARY_AVAILABILITY_SIGNAL"


def test_rotowire_empty_or_unparseable_body_fails_closed():
    assert parse_rotowire_lineups("") == {"fixtures": [], "lineups": [], "availability": []}
