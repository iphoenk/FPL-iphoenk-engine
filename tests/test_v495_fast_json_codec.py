from src import utils


def test_fast_json_codec_preserves_unicode_non_string_keys_and_pretty_artifacts(tmp_path):
    path = tmp_path / "artifact.json"
    payload = {"text": "kapten Ødegaard", "nested": {1: [1, 2, 3]}, "flag": True}
    utils.atomic_json(path, payload)
    restored = utils.read_json(path)
    assert restored == {"text": "kapten Ødegaard", "nested": {"1": [1, 2, 3]}, "flag": True}
    raw = path.read_bytes()
    assert b"\n" in raw
    assert "Ødegaard" in raw.decode("utf-8")


def test_large_prediction_machine_artifacts_are_compact_without_semantic_change(tmp_path):
    payload = {"text": "kapten Ødegaard", "players": [{"element": 1, "xpts": 5.25}], "nested": {1: True}}
    for name in ("predictions_v4.json", "predictions_base_hot_cache_v4.json"):
        path = tmp_path / name
        utils.atomic_json(path, payload)
        raw = path.read_bytes()
        assert b"\n" not in raw
        assert utils.read_json(path) == {
            "text": "kapten Ødegaard",
            "players": [{"element": 1, "xpts": 5.25}],
            "nested": {"1": True},
        }


def test_jsonl_codec_remains_one_object_per_line(tmp_path):
    path = tmp_path / "history.jsonl"
    utils.append_jsonl(path, {"a": 1})
    utils.append_jsonl(path, {"b": 2})
    lines = path.read_bytes().splitlines()
    assert len(lines) == 2
    assert utils._loads(lines[0]) == {"a": 1}
    assert utils._loads(lines[1]) == {"b": 2}
