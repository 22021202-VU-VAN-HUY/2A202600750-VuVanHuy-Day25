from __future__ import annotations

import argparse
import json
from pathlib import Path

from reliability_lab.config import load_config


def _load_json(path: str | Path) -> dict[str, object]:
    json_path = Path(path)
    if not json_path.exists():
        return {}
    return json.loads(json_path.read_text())


def _value(data: dict[str, object], key: str, default: object = 0) -> object:
    return data.get(key, default)


def _fmt(value: object) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _met(actual: object, target: float, op: str) -> str:
    if actual is None:
        return "N/A"
    actual_float = float(actual)
    if op == ">=":
        return "Yes" if actual_float >= target else "No"
    return "Yes" if actual_float < target else "No"


def _comparison_row(
    comparison: dict[str, object],
    metric: str,
    label: str,
    lower_is_better: bool = False,
) -> str:
    without_cache = comparison.get("without_cache", {})
    with_cache = comparison.get("with_cache", {})
    if not isinstance(without_cache, dict) or not isinstance(with_cache, dict):
        return f"| {label} | N/A | N/A | N/A |"
    before = float(without_cache.get(metric, 0) or 0)
    after = float(with_cache.get(metric, 0) or 0)
    delta = after - before
    delta_text = f"{delta:.4f}"
    if lower_is_better:
        delta_text = f"{delta_text} (lower is better)"
    return f"| {label} | {before:.4f} | {after:.4f} | {delta_text} |"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", default="reports/metrics.json")
    parser.add_argument("--out", default="reports/final_report.md")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--cache-comparison", default="reports/cache_comparison.json")
    parser.add_argument("--redis-evidence", default="reports/redis_evidence.json")
    args = parser.parse_args()

    metrics = _load_json(args.metrics)
    comparison = _load_json(args.cache_comparison)
    redis_evidence = _load_json(args.redis_evidence)
    config = load_config(args.config)

    cb = config.circuit_breaker
    cache = config.cache
    scenarios = metrics.get("scenarios", {})
    scenario_statuses = scenarios if isinstance(scenarios, dict) else {}
    requests_per_comparison = comparison.get("requests_per_scenario", "N/A")
    redis_keys = redis_evidence.get("keys", [])
    redis_keys_text = "\n".join(str(key) for key in redis_keys) if redis_keys else "(no keys captured)"

    lines = [
        "# Day 10 Reliability Final Report",
        "",
        "**Họ và tên:** Vũ Văn Huy",
        "",
        "**Mã học viên:** 2A202600750",
        "",
        "## 1. Architecture summary",
        "",
        "The gateway first checks the cache, then routes provider calls through per-provider "
        "circuit breakers. If the primary path fails or is open, traffic falls back to the "
        "backup provider. If every provider fails, the gateway returns a static degraded "
        "message instead of raising an uncaught error.",
        "",
        "```text",
        "User Request",
        "    |",
        "    v",
        "[ReliabilityGateway]",
        "    |",
        "    +--> [ResponseCache / SharedRedisCache] -- HIT --> cached response",
        "    |",
        "    v MISS",
        "[CircuitBreaker: primary] --> FakeLLMProvider primary",
        "    | fail/open",
        "    v",
        "[CircuitBreaker: backup]  --> FakeLLMProvider backup",
        "    | fail/open",
        "    v",
        "[Static fallback response]",
        "```",
        "",
        "## 2. Configuration",
        "",
        "| Setting | Value | Reason |",
        "|---|---:|---|",
        (
            f"| failure_threshold | {cb.failure_threshold} | "
            "Open after repeated failures to stop retry storms. |"
        ),
        (
            f"| reset_timeout_seconds | {cb.reset_timeout_seconds} | "
            "Wait before a half-open probe. |"
        ),
        f"| success_threshold | {cb.success_threshold} | Close after successful probe(s). |",
        (
            f"| cache TTL | {cache.ttl_seconds} | "
            "Keeps repeated lab prompts warm without keeping data forever. |"
        ),
        (
            f"| similarity_threshold | {cache.similarity_threshold} | "
            "Conservative threshold to reduce false semantic hits. |"
        ),
        (
            f"| load_test requests | {config.load_test.requests} | "
            "Enough requests to show cache and fallback behavior. |"
        ),
        "",
        "## 3. SLO definitions",
        "",
        "| SLI | SLO target | Actual value | Met? |",
        "|---|---|---:|---|",
        (
            f"| Availability | >= 99% | {_fmt(_value(metrics, 'availability'))} | "
            f"{_met(_value(metrics, 'availability'), 0.99, '>=')} |"
        ),
        (
            f"| Latency P95 | < 2500 ms | {_fmt(_value(metrics, 'latency_p95_ms'))} | "
            f"{_met(_value(metrics, 'latency_p95_ms'), 2500, '<')} |"
        ),
        (
            f"| Fallback success rate | >= 95% | "
            f"{_fmt(_value(metrics, 'fallback_success_rate'))} | "
            f"{_met(_value(metrics, 'fallback_success_rate'), 0.95, '>=')} |"
        ),
        (
            f"| Cache hit rate | >= 10% | {_fmt(_value(metrics, 'cache_hit_rate'))} | "
            f"{_met(_value(metrics, 'cache_hit_rate'), 0.10, '>=')} |"
        ),
        (
            f"| Recovery time | < 5000 ms | {_fmt(_value(metrics, 'recovery_time_ms', None))} | "
            f"{_met(_value(metrics, 'recovery_time_ms', None), 5000, '<')} |"
        ),
        "",
        "## 4. Metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]

    for key, value in metrics.items():
        if key == "scenarios":
            continue
        lines.append(f"| {key} | {value} |")

    lines += [
        "",
        "## 5. Cache comparison",
        "",
        f"Comparison run size: {requests_per_comparison} requests per scenario.",
        "",
        "| Metric | Without cache | With cache | Delta |",
        "|---|---:|---:|---|",
        _comparison_row(comparison, "latency_p50_ms", "latency_p50_ms", True),
        _comparison_row(comparison, "latency_p95_ms", "latency_p95_ms", True),
        _comparison_row(comparison, "estimated_cost", "estimated_cost", True),
        _comparison_row(comparison, "cache_hit_rate", "cache_hit_rate"),
        "",
        "## 6. Redis shared cache",
        "",
        "- In-memory cache is per process, so multiple gateway instances would not share hits.",
        "- `SharedRedisCache` stores query/response hashes in Redis with TTL, so separate "
        "instances can reuse the same cached response.",
        "",
        "### Evidence of shared state",
        "",
        "```json",
        json.dumps(redis_evidence, indent=2, ensure_ascii=False),
        "```",
        "",
        "### Redis CLI output",
        "",
        "```text",
        redis_keys_text,
        "```",
        "",
        "## 7. Chaos scenarios",
        "",
        "| Scenario | Expected behavior | Observed behavior | Pass/Fail |",
        "|---|---|---|---|",
        (
            "| primary_timeout_100 | Primary fails; backup handles traffic and circuit opens. | "
            f"Combined run recorded {_value(metrics, 'circuit_open_count')} open transitions. | "
            f"{scenario_statuses.get('primary_timeout_100', 'N/A')} |"
        ),
        (
            "| primary_flaky_50 | Primary intermittently fails; fallback absorbs failures. | "
            f"Fallback success rate was {_fmt(_value(metrics, 'fallback_success_rate'))}. | "
            f"{scenario_statuses.get('primary_flaky_50', 'N/A')} |"
        ),
        (
            "| all_healthy | Providers stay healthy; no scenario-level failure expected. | "
            f"Overall availability was {_fmt(_value(metrics, 'availability'))}. | "
            f"{scenario_statuses.get('all_healthy', 'N/A')} |"
        ),
        "",
        "## 8. Failure analysis",
        "",
        "One remaining weakness is that circuit breaker state is local to each process. In a "
        "multi-instance deployment, one instance may open its breaker while another keeps "
        "sending traffic to the failing provider. Before production, I would move breaker "
        "counters and transition state into Redis with atomic increments and short TTLs.",
        "",
        "## 9. Next steps",
        "",
        "1. Add distributed circuit breaker state in Redis.",
        "2. Add per-provider latency/error dashboards and alert thresholds.",
        "3. Add concurrency load tests to measure retry-storm behavior under parallel traffic.",
    ]

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
