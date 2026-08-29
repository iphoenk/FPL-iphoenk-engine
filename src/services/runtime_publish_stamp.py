from __future__ import annotations

from src.engines.v4_freshness import evaluate_freshness
from src.utils import DATA, atomic_json, iso_now, read_json

LATEST=DATA/"latest.json";CHECKPOINT=DATA/"checkpoint_decision_v4.json";SERVING=DATA/"serving_payload_v4.json";BENCHMARK=DATA/"serving_benchmark_v4.json"


def stamp_runtime_publish(published_at: str | None = None) -> dict:
    stamp=published_at or iso_now();latest=read_json(LATEST,{})
    if not latest:raise RuntimeError("runtime publish stamp requires latest.json")
    latest["runtime_publish_at"]=stamp;freshness=evaluate_freshness(latest,now=stamp,runtime_publish_at=stamp);latest["freshness"]=freshness;latest["source_age_minutes"]=freshness.get("source_age_minutes");latest["freshness_state"]=freshness.get("freshness_state");atomic_json(LATEST,latest)
    checkpoint=read_json(CHECKPOINT,{})
    if checkpoint:
        checkpoint["runtime_publish_at"]=stamp;checkpoint["freshness_at_publish"]=freshness;atomic_json(CHECKPOINT,checkpoint)
    serving=read_json(SERVING,{})
    if serving:
        serving["runtime_publish_at"]=stamp;engine_line=serving.setdefault("engine_source_line",{});engine_line["freshness_at_publish"]=freshness;atomic_json(SERVING,serving)
    benchmark=read_json(BENCHMARK,{})
    if benchmark:
        benchmark["runtime_publish_at"]=stamp;benchmark["publication_source_age_minutes"]=freshness.get("source_age_minutes");atomic_json(BENCHMARK,benchmark)
    return {"runtime_publish_at":stamp,"freshness_state":freshness.get("freshness_state"),"source_age_minutes":freshness.get("source_age_minutes")}


def main():print(stamp_runtime_publish())
if __name__=="__main__":main()
