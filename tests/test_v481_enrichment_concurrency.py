import src.services.enrichment_service as service


def test_enrichment_submits_all_sources_before_waiting(monkeypatch):
    submitted = []

    class Future:
        def __init__(self, name):
            self.name = name

        def result(self):
            assert submitted == ["a", "b", "c"]
            return self.name

    class Executor:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def submit(self, fn):
            name = fn()
            submitted.append(name)
            return Future(name)

    monkeypatch.setattr(service, "ThreadPoolExecutor", Executor)
    result = service._run_parallel({name: (lambda value=name: value) for name in ("a", "b", "c")})

    assert result == {"a": "a", "b": "b", "c": "c"}
