from __future__ import annotations

import os

from src.runtime_v3 import incremental_reuse


def test_generic_json_digest_cache_reuses_same_stat_key(tmp_path):
    path = tmp_path / "payload.json"
    path.write_text('{"generated_at":"a","value":1}\n', encoding="utf-8")
    stat = path.stat()
    incremental_reuse._digest_file_cached.cache_clear()
    first = incremental_reuse._digest_file_cached("GENERIC_JSON", str(path), stat.st_size, stat.st_mtime_ns)
    second = incremental_reuse._digest_file_cached("GENERIC_JSON", str(path), stat.st_size, stat.st_mtime_ns)
    assert first == second
    info = incremental_reuse._digest_file_cached.cache_info()
    assert info.hits >= 1


def test_stat_key_invalidates_when_same_size_content_changes(tmp_path):
    path = tmp_path / "payload.json"
    path.write_text('{"value":1}\n', encoding="utf-8")
    first_stat = path.stat()
    incremental_reuse._digest_file_cached.cache_clear()
    first = incremental_reuse._digest_file_cached("GENERIC_JSON", str(path), first_stat.st_size, first_stat.st_mtime_ns)

    path.write_text('{"value":2}\n', encoding="utf-8")
    os.utime(path, ns=(first_stat.st_atime_ns, first_stat.st_mtime_ns + 1_000_000))
    second_stat = path.stat()
    second = incremental_reuse._digest_file_cached("GENERIC_JSON", str(path), second_stat.st_size, second_stat.st_mtime_ns)
    assert first_stat.st_size == second_stat.st_size
    assert first_stat.st_mtime_ns != second_stat.st_mtime_ns
    assert first != second


def test_generic_json_semantics_ignore_volatile_generated_at(tmp_path):
    path = tmp_path / "payload.json"
    path.write_text('{"generated_at":"a","value":1}\n', encoding="utf-8")
    first_stat = path.stat()
    incremental_reuse._digest_file_cached.cache_clear()
    first = incremental_reuse._digest_file_cached("GENERIC_JSON", str(path), first_stat.st_size, first_stat.st_mtime_ns)

    path.write_text('{"generated_at":"b","value":1}\n', encoding="utf-8")
    second_stat = path.stat()
    second = incremental_reuse._digest_file_cached("GENERIC_JSON", str(path), second_stat.st_size, second_stat.st_mtime_ns)
    assert first == second
