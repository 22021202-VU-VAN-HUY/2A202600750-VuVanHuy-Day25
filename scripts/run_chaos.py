from __future__ import annotations

import argparse
import json
from pathlib import Path

from reliability_lab.cache import SharedRedisCache
from reliability_lab.chaos import load_queries, run_simulation
from reliability_lab.config import LabConfig, load_config


def write_cache_comparison(config: LabConfig, queries: list[str], path: str | Path) -> None:
    """Write a small reproducible cache-on/cache-off comparison."""
    requests = min(config.load_test.requests, 30)
    base_config = config.model_copy(
        update={"load_test": config.load_test.model_copy(update={"requests": requests})}
    )
    without_cache_config = base_config.model_copy(
        update={"cache": base_config.cache.model_copy(update={"enabled": False})}
    )
    with_cache_config = base_config.model_copy(
        update={
            "cache": base_config.cache.model_copy(
                update={"enabled": True, "backend": "memory"}
            )
        }
    )
    comparison = {
        "requests_per_scenario": requests,
        "without_cache": run_simulation(without_cache_config, queries).to_report_dict(),
        "with_cache": run_simulation(with_cache_config, queries).to_report_dict(),
    }
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(comparison, indent=2, ensure_ascii=False))


def write_redis_evidence(config: LabConfig, path: str | Path) -> None:
    """Write proof that two cache instances share Redis state."""
    caches: list[SharedRedisCache] = []
    try:
        cache_a = SharedRedisCache(
            config.cache.redis_url,
            config.cache.ttl_seconds,
            config.cache.similarity_threshold,
        )
        cache_b = SharedRedisCache(
            config.cache.redis_url,
            config.cache.ttl_seconds,
            config.cache.similarity_threshold,
        )
        caches.extend([cache_a, cache_b])
        cache_a.flush()
        query = "Redis shared cache evidence query"
        response = "shared response from instance A"
        cache_a.set(query, response)
        cached, score = cache_b.get(query)
        evidence = {
            "available": cache_a.ping(),
            "shared_state_ok": cached == response,
            "query": query,
            "cached_response_from_second_instance": cached,
            "score": score,
            "keys": list(cache_a._redis.scan_iter(f"{cache_a.prefix}*")),
        }
    except Exception as exc:
        evidence = {"available": False, "shared_state_ok": False, "error": str(exc)}
    finally:
        for cache in caches:
            cache.close()

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--out", default="reports/metrics.json")
    args = parser.parse_args()
    config = load_config(args.config)
    queries = load_queries()
    metrics = run_simulation(config, queries)
    metrics.write_json(args.out)
    metrics.write_csv(Path(args.out).with_suffix(".csv"))
    write_cache_comparison(config, queries, Path(args.out).with_name("cache_comparison.json"))
    write_redis_evidence(config, Path(args.out).with_name("redis_evidence.json"))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
