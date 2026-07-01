# Báo cáo cuối lab Day 10 - Reliability Engineering

**Họ và tên:** Vũ Văn Huy

**Mã học viên:** 2A202600750

## 1. Tóm tắt kiến trúc

Gateway kiểm tra cache trước, sau đó định tuyến request qua circuit breaker riêng cho từng provider. Nếu primary provider lỗi hoặc circuit đang mở, request sẽ được chuyển sang backup provider. Nếu tất cả provider đều lỗi, gateway trả về thông báo static fallback thay vì để hệ thống ném lỗi không kiểm soát.

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

## 2. Cấu hình

| Thiết lập | Giá trị | Lý do |
|---|---:|---|
| failure_threshold | 3 | Mở circuit sau nhiều lần lỗi liên tiếp để tránh retry storm. |
| reset_timeout_seconds | 2.0 | Chờ trước khi cho request probe ở trạng thái half-open. |
| success_threshold | 1 | Đóng circuit sau khi probe thành công. |
| cache TTL | 300 | Giữ cache đủ lâu cho các prompt lặp lại trong lab nhưng không lưu vô thời hạn. |
| similarity_threshold | 0.92 | Ngưỡng cao để giảm nguy cơ cache hit sai về mặt ngữ nghĩa. |
| load_test requests | 100 | Đủ request để quan sát hành vi cache, fallback và circuit breaker. |

## 3. Định nghĩa SLO

| SLI | Mục tiêu SLO | Giá trị thực tế | Đạt? |
|---|---|---:|---|
| Availability | >= 99% | 0.9900 | Có |
| Latency P95 | < 2500 ms | 307.0800 | Có |
| Fallback success rate | >= 95% | 0.9559 | Có |
| Cache hit rate | >= 10% | 0.5733 | Có |
| Recovery time | < 5000 ms | 2230.8190 | Có |

## 4. Metrics

| Metric | Giá trị |
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

## 5. So sánh cache

Kích thước lần chạy so sánh: 30 request cho mỗi scenario.

| Metric | Không dùng cache | Có dùng cache | Chênh lệch |
|---|---:|---:|---|
| latency_p50_ms | 267.6500 | 265.3000 | -2.3500, thấp hơn là tốt hơn |
| latency_p95_ms | 313.0800 | 306.4800 | -6.6000, thấp hơn là tốt hơn |
| estimated_cost | 0.0400 | 0.0242 | -0.0158, thấp hơn là tốt hơn |
| cache_hit_rate | 0.0000 | 0.3778 | 0.3778 |

Kết quả cho thấy cache giúp giảm latency P50/P95, giảm estimated cost và tạo cache hit rate rõ ràng trong lần chạy so sánh.

## 6. Redis shared cache

- In-memory cache chỉ tồn tại trong một process, nên nhiều gateway instance sẽ không chia sẻ được cache hit.
- `SharedRedisCache` lưu query/response trong Redis hash kèm TTL, vì vậy nhiều instance khác nhau có thể dùng chung dữ liệu cache.
- Privacy guardrail vẫn được áp dụng để không cache các query nhạy cảm như password, account balance, SSN hoặc thông tin tài khoản.

### Bằng chứng shared state

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

| Scenario | Kỳ vọng | Quan sát thực tế | Pass/Fail |
|---|---|---|---|
| primary_timeout_100 | Primary provider lỗi; backup xử lý traffic và circuit mở. | Lần chạy tổng hợp ghi nhận 7 lần circuit chuyển sang open. | pass |
| primary_flaky_50 | Primary lỗi không ổn định; fallback hấp thụ các lỗi. | Fallback success rate đạt 0.9559. | pass |
| all_healthy | Provider khỏe mạnh; không kỳ vọng lỗi ở scenario này. | Availability tổng thể đạt 0.9900. | pass |

## 8. Phân tích điểm yếu còn lại

Điểm yếu còn lại là trạng thái circuit breaker hiện vẫn nằm local trong từng process. Trong deployment nhiều instance, một instance có thể đã mở circuit nhưng instance khác vẫn tiếp tục gửi request tới provider đang lỗi. Trước khi đưa vào production, nên đưa counter và trạng thái circuit breaker vào Redis bằng các thao tác atomic như `INCR`, `EXPIRE` và key TTL ngắn.

## 9. Hướng cải thiện tiếp theo

1. Thêm distributed circuit breaker state trong Redis.
2. Thêm dashboard theo dõi latency/error theo từng provider và thiết lập alert threshold.
3. Thêm concurrency load test để đo retry-storm behavior khi có nhiều request song song.
