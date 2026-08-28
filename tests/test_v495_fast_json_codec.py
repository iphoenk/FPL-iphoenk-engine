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


def test_jsonl_codec_remains_one_object_per_line(tmp_path):
    path = tmp_path / "history.jsonl"
    utils.append_jsonl(path, {"a": 1})
    utils.append_jsonl(path, {"b": 2})
    lines = path.read_bytes().splitlines()
    assert len(lines) == 2
    assert utils._loads(lines[0]) == {"a": 1}
    assert utils._loads(lines[1]) == {"b": 2}
