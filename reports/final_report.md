# Day 10 Reliability Final Report

**Họ và tên:** Vũ Văn Huy

**Mã học viên:** 2A202600750

## 1. Architecture summary

The gateway first checks the cache, then routes provider calls through per-provider circuit breakers. If the primary path fails or is open, traffic falls back to the backup provider. If every provider fails, the gateway returns a static degraded message instead of raising an uncaught error.

```text
User Request
    |
    v
[ReliabilityGateway]
    |
    +--> [ResponseCache / SharedRedisCache] -- HIT --> cached response
    |
    v MISS
[CircuitBreaker: primary] --> FakeLLMProvider primary
    | fail/open
    v
[CircuitBreaker: backup]  --> FakeLLMProvider backup
    | fail/open
    v
[Static fallback response]
```

## 2. Configuration

| Setting | Value | Reason |
|---|---:|---|
| failure_threshold | 3 | Open after repeated failures to stop retry storms. |
| reset_timeout_seconds | 2.0 | Wait before a half-open probe. |
| success_threshold | 1 | Close after successful probe(s). |
| cache TTL | 300 | Keeps repeated lab prompts warm without keeping data forever. |
| similarity_threshold | 0.92 | Conservative threshold to reduce false semantic hits. |
| load_test requests | 100 | Enough requests to show cache and fallback behavior. |

## 3. SLO definitions

| SLI | SLO target | Actual value | Met? |
|---|---|---:|---|
| Availability | >= 99% | 0.9900 | Yes |
| Latency P95 | < 2500 ms | 307.0800 | Yes |
| Fallback success rate | >= 95% | 0.9559 | Yes |
| Cache hit rate | >= 10% | 0.5733 | Yes |
| Recovery time | < 5000 ms | 2230.8190 | Yes |

## 4. Metrics

| Metric | Value |
|---|---:|
| total_requests | 300 |
| availability | 0.99 |
| error_rate | 0.01 |
| latency_p50_ms | 265.15 |
| latency_p95_ms | 307.08 |
| latency_p99_ms | 320.07 |
| fallback_success_rate | 0.9559 |
| cache_hit_rate | 0.5733 |
| circuit_open_count | 7 |
| recovery_time_ms | 2230.8189868927 |
| estimated_cost | 0.055586 |
| estimated_cost_saved | 0.172 |

## 5. Cache comparison

Comparison run size: 30 requests per scenario.

| Metric | Without cache | With cache | Delta |
|---|---:|---:|---|
| latency_p50_ms | 267.6500 | 265.3000 | -2.3500 (lower is better) |
| latency_p95_ms | 313.0800 | 306.4800 | -6.6000 (lower is better) |
| estimated_cost | 0.0400 | 0.0242 | -0.0158 (lower is better) |
| cache_hit_rate | 0.0000 | 0.3778 | 0.3778 |

## 6. Redis shared cache

- In-memory cache is per process, so multiple gateway instances would not share hits.
- `SharedRedisCache` stores query/response hashes in Redis with TTL, so separate instances can reuse the same cached response.

### Evidence of shared state

```json
{
  "available": true,
  "shared_state_ok": true,
  "query": "Redis shared cache evidence query",
  "cached_response_from_second_instance": "shared response from instance A",
  "score": 1.0,
  "keys": [
    "rl:cache:732298515b35"
  ]
}
```

### Redis CLI output

```text
rl:cache:732298515b35
```

## 7. Chaos scenarios

| Scenario | Expected behavior | Observed behavior | Pass/Fail |
|---|---|---|---|
| primary_timeout_100 | Primary fails; backup handles traffic and circuit opens. | Combined run recorded 7 open transitions. | pass |
| primary_flaky_50 | Primary intermittently fails; fallback absorbs failures. | Fallback success rate was 0.9559. | pass |
| all_healthy | Providers stay healthy; no scenario-level failure expected. | Overall availability was 0.9900. | pass |

## 8. Failure analysis

One remaining weakness is that circuit breaker state is local to each process. In a multi-instance deployment, one instance may open its breaker while another keeps sending traffic to the failing provider. Before production, I would move breaker counters and transition state into Redis with atomic increments and short TTLs.

## 9. Next steps

1. Add distributed circuit breaker state in Redis.
2. Add per-provider latency/error dashboards and alert thresholds.
3. Add concurrency load tests to measure retry-storm behavior under parallel traffic.