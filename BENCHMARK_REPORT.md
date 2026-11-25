# Benchmark & Observability Report — Day 14

> Mọi con số ở mục 2 và 3 lấy từ file JSON trong [`reports/`](reports/) (bản gốc nằm ở `06-lab-complete/benchmark-observability/develop/reports/`; kèm log console `.txt` cùng tên).
> Ba file `load_v2_slow_*.json` lúc chạy được lưu với tên `load_v2_slow<x>.json`, sau đó đổi tên cho đúng SUBMISSION.md; nội dung giữ nguyên (log `.txt` vẫn in tên cũ).
> Các mục 4 và 5 cần Docker (Prometheus, Grafana, Jaeger, Locust). Ô nào đánh dấu **⏳** là chưa có số đo thật: phải chạy stack rồi điền, không ước lượng.

**Họ tên:** Nguyen Khoi Nguyen — 2A202603453
**Ngày chạy:** 2026-11-25
**Môi trường:** Windows 11 Home, Intel Core i7-12650H (10 cores / 16 threads), 15.7 GB RAM, Python 3.11.9. Agent `develop/app.py` chạy 1 process uvicorn, load test chạy cùng máy.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < **500 ms** | Mock LLM mất khoảng 150–230 ms mỗi call (120 ms base + jitter + retrieval), nên 500 ms còn hơn gấp 2 lần cho queueing. Người dùng chat cảm thấy "tức thì" dưới khoảng 0.5 s. p95 bỏ qua 3% request chậm do upstream LLM (cái đó theo dõi riêng bằng p99). Alert đặt lỏng hơn (p95 > 1 s trong 2 phút) để tránh alert fatigue. |
| Error rate `/ask` | < **2 %** | Mock LLM lỗi upstream khoảng 1% (`MOCK_ERROR_RATE=0.01`), nên SLO 2% chừa 1% error budget cho lỗi của chính mình. Alert ở 5% trong 1 phút để chỉ báo khi sự cố rõ rệt và kéo dài. |
| Accuracy trên golden dataset | ≥ **85 %** (gate CI) và **không regression** | Sau khi sửa KB, v2 đạt 100%. Ngưỡng 85% (khoảng ≤ 3/23 câu sai) đủ chặt để bắt regression lớn mà không fail CI vì 1 câu flaky. Thêm điều kiện "không câu nào từ đúng thành sai" để bắt regression nhỏ. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

Lệnh: `python load_test.py --url http://localhost:8002 --requests 300 --concurrency <N> --out reports/load_v2_c<N>.json`

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO (p95 ≤ 500ms, err ≤ 2%) |
|---|---|---|---|---|---|---|
| 1 | 3.81 | 209.6 | 251.6 | 1713.7 | 1.00% | ✅ PASS |
| 10 | 35.61 | 205.2 | 537.5 | 1717.6 | 0.67% | ❌ FAIL (p95) |
| 50 | 51.48 | 359.7 | 2967.0 | 3836.0 | 1.67% | ❌ FAIL (p95) |
| 100 | 32.24 | 1001.1 | 6895.1 | 7702.9 | 1.00% | ❌ FAIL (p95) |

**Nhận xét:** RPS **chỉ tăng gần tuyến tính ở mức tải thấp** (1 → 10: ×9.3 RPS với ×10 concurrency, p50 không đổi khoảng 205 ms). Theo định luật Little: RPS ≈ concurrency / latency ≈ 10 / 0.26 s ≈ 38, khớp với số đo 35.6.

Từ 10 → 50, RPS chỉ tăng ×1.45 trong khi p50 tăng từ 205 lên 360 ms. Từ 50 → 100, RPS còn **giảm** (51 → 32) và p95 lên gần 7 s. Mock LLM là `asyncio.sleep` nên về lý thuyết không giới hạn. Nút thắt là **CPU của 1 process uvicorn duy nhất** (1 event loop xử lý HTTP parsing, Pydantic, Prometheus metrics, ghi log JSON mỗi request), cộng thêm việc client load test chạy cùng máy và tranh CPU. Khi event loop bão hoà, request phải xếp hàng, nên latency tăng nhưng throughput không tăng (thậm chí giảm vì overhead context switch và connection). Muốn tăng tiếp thì phải scale ngang (nhiều worker/instance, xem mục 5), không thể chỉ tăng concurrency.

Error rate ổn định khoảng 1% ở mọi mức tải. Đó là lỗi upstream giả lập (503), không tăng theo tải.

### 2.2 Tail latency

Lệnh: restart agent v2 với `MOCK_SLOW_RATE=<x>`, chạy `--requests 300 --concurrency 20` (file `reports/load_v2_slow_<x>.json`)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) | max (ms) |
|---|---|---|---|---|
| 0 | 231.1 | 526.3 | 588.5 | 615.4 |
| 0.03 (mặc định) | 271.2 | 503.8 | 1735.4 | 1748.7 |
| 0.1 | 344.4 | 1697.3 | 1727.0 | 2043.1 |

**Nhận xét:**
- Từ 0 lên 0.03, **avg chỉ tăng 17%** (231 → 271 ms) và p95 gần như không đổi. Riêng **p99 tăng gần 3 lần** (589 → 1735 ms): 3% request chậm nằm đúng trên ngưỡng 99%.
- Từ 0.03 lên 0.1, tỉ lệ request chậm (10%) vượt quá 5% nên **p95 nhảy vọt** lên 1697 ms (×3.4), trong khi avg chỉ tăng 27%.
- **Percentile cao nhạy nhất với request chậm.** Request chậm chỉ chiếm vài % nên kéo average lên rất ít ((97×230 + 3×1730)/100 ≈ 275 ms). Nhưng với 3% người dùng đó, họ phải chờ gần 2 giây. Average che mất trải nghiệm tệ của nhóm này, nên SLO phải đặt theo **p95/p99**.
- (Ở mức 0, p95 = 526 ms là do queueing khi chạy 20 concurrency trên Windows, không phải do request chậm: max chỉ 615 ms.)

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | **100% (23/23)** |
| Avg tokens / câu | 57.1 | 109.0 | 113.7 |
| Tổng cost (USD) | 0.000404 | 0.000760 | 0.000790 |
| Cost / câu đúng (USD) | 0.00040395 | 0.00003619 | 0.00003436 |
| Latency p50 / p95 (ms) | 171.2 / 1681.8 | 208.5 / 1738.6 | 202.3 / 1535.4 |
| Quality gate | **FAIL** (< 80%) | **PASS** (≥ 80%, 0 regression vs v1) | **PASS** (`--min-accuracy 1.0`, 0 regression vs v2) |

File: `reports/eval_v1.json`, `reports/eval_v2.json` (`--baseline eval_v1.json`), `reports/eval_v2_fixed.json` (`--baseline eval_v2.json --min-accuracy 1.0`).

**Những câu v2 trả lời sai ban đầu và cách sửa:**

| ID | Keyword bị thiếu | Đã sửa gì |
|---|---|---|
| `scaling-03` (Kubernetes HPA scale dựa trên chỉ số nào?) | `cpu`, `memory`, `custom metrics` | KB không có tài liệu nào về HPA nên retrieval không tìm được gì, agent trả câu generic. Thêm entry `(["hpa", "kubernetes", "autoscal"], "Kubernetes HPA ... scale số pod dựa trên CPU, memory hoặc custom metrics như RPS hay độ dài hàng đợi.")` vào `KNOWLEDGE_BASE` |
| `security-02` (JWT khác gì API key?) | `token`, `hết hạn`, `chữ ký` | KB chưa có tài liệu về JWT. Thêm entry `(["jwt"], "API key là chuỗi bí mật cố định, không tự hết hạn. JWT là token có chữ ký số, chứa thông tin user và thời điểm hết hạn; ...")` |

Sửa ở cả `develop/utils/mock_llm.py` và `production/utils/mock_llm.py`. Keyword mới (`hpa`, `kubernetes`, `autoscal`, `jwt`) không xuất hiện trong câu hỏi nào khác nên không cướp retrieval của câu khác: **0 regression**.

**Quality gate ngược (Bài tập 4):** chạy eval v1 với `--baseline reports/eval_v2.json` thì **exit code 1**, 20 câu regression (`reports/eval_v1_vs_v2_gate.txt`). Lệnh này dùng làm bước CI chặn merge, xem [`.github/workflows/quality-gate.yml`](.github/workflows/quality-gate.yml) (fail nếu accuracy < 85% hoặc có regression). `run_eval.py` kết thúc bằng `raise SystemExit(0 if gate_ok else 1)`; GitHub Actions coi exit code ≠ 0 là step fail, nên job fail. Đặt job này làm *required status check* trong branch protection thì PR không merge được.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**
- v2 (RAG) tốn **×1.9 token mỗi câu** (prompt chứa thêm context) và **×1.9 tổng chi phí**, latency p50 tăng khoảng 37 ms (bước retrieval khoảng 20 ms cộng prompt dài hơn làm LLM chậm hơn).
- Đổi lại accuracy tăng từ 4.3% lên 91–100%, nên **cost trên mỗi câu đúng giảm khoảng 11–12 lần** ($0.000404 → $0.000034). v1 rẻ trên mỗi request nhưng gần như mọi câu trả lời đều vô dụng, nên thực ra là phương án đắt nhất.
- Sửa KB thêm 2 tài liệu chỉ tăng khoảng 4% token nhưng tăng accuracy 8.7 điểm %, rất đáng.

---

## 4. Observability stack (production)

> ⏳ **Chưa chạy được trên máy làm bài** vì không có Docker. Cách hoàn thành (CHECKPOINTS CP8): `cd 06-lab-complete/benchmark-observability/production && docker compose -p k5-day14-observability up -d --build --scale agent=1` → làm theo mục 2.2–2.6 của README Part 7 → chụp 4 screenshot vào `screenshots/` → điền bảng dưới.
> Unit test alert rules và Locust CSV có thể lấy từ GitHub Actions: workflow [`benchmark-production`](.github/workflows/benchmark-production.yml).

### 4.1 Screenshot

- [ ] Dashboard Grafana khi đang có tải → `screenshots/grafana-dashboard.png`
- [ ] Một trace chậm trong Jaeger → `screenshots/jaeger-slow-trace.png`
- [ ] Một trace lỗi trong Jaeger (có event `exception`) → `screenshots/jaeger-error-trace.png`
- [ ] Trang Alerts của Prometheus thấy **≥ 2 alert cùng firing trong 1 ảnh** (RUBRIC) → `screenshots/prometheus-alert-firing.png`

### 4.2 Thí nghiệm "phá hệ thống"

Cột "Thời gian tối thiểu theo rule" tính từ `alert_rules.yml` (scrape/evaluation 5s, window `rate[1m]` hoặc `[5m]`, `for`). Cột đo thật phải điền từ quan sát.

| # | Thay đổi | Alert nào firing | Thời gian tối thiểu theo rule | Thời gian đo thật (đổi → firing) | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (5xx/total > 5%) | khoảng 15–30s để `rate[1m]` vượt 5% + `for: 1m`, tổng khoảng 1–1.5 phút | ⏳ | Error rate (Golden Signals) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (p95 > 1s) | 30% request chậm hơn 1.5s nên p95 > 1s sau khoảng 15–30s + `for: 2m`, tổng khoảng 2–2.5 phút | ⏳ | Latency p50/p95/p99/avg |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (> $2/giờ) *nếu tải đủ lớn* | `rate[5m]` cần vài phút để tăng + `for: 2m`, khoảng 3–5 phút. Ước tính: 30 users, `wait_time` 0.5–2s cho khoảng 18 RPS `/ask` × khoảng $0.0008/request (large đắt ×16) ≈ $50/giờ, vượt xa $2 | ⏳ | Cost USD/giờ, LLM p95 |
| D | `docker pause` 1 instance | `AgentInstanceDown` (`up == 0`) | scrape fail ngay (5s) + `for: 30s`, khoảng 35–45s | ⏳ | Instances up |
| E | `AGENT_VERSION=v1` | **Không có** | — | — | Retrieval hit ratio, bảng version, tokens/s giảm |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Đây là **lỗi chất lượng**, không phải lỗi hạ tầng: v1 vẫn trả 200 nhanh, rẻ, nên mọi Golden Signal vẫn xanh. Cách phát hiện:
1. **Chặn trước khi deploy:** eval golden dataset trong CI (quality gate). v1 so với baseline v2 có 20 regression và exit 1, nên không merge/deploy được.
2. **Metric "proxy" cho chất lượng** có alert: `retrieval hit ratio` giảm đột ngột, `llm_tokens_total{type="input"}` mỗi request giảm mạnh, `agent_info{version}` thay đổi ngoài lịch release.
3. **Online eval / feedback:** lấy mẫu khoảng 1–5% traffic thật để chấm bằng LLM-as-judge hoặc so với tài liệu, rồi theo dõi tỉ lệ 👍/👎 và tỉ lệ hỏi lại câu tương tự của người dùng.
4. **Synthetic check:** cron định kỳ gửi vài câu hỏi golden vào production, alert nếu câu trả lời thiếu keyword.

### 4.3 Debug bằng trace

> ⏳ Điền sau khi chạy stack: Jaeger → Service `observable-agent` → Find Traces → **Longest First**.

- `trace_id`: ⏳
- Tổng thời gian: ⏳ ms
- Span chiếm nhiều thời gian nhất: ⏳ (dự đoán theo kiến trúc: `chat mock-llm-small`, tức LLM call, khoảng 98% thời gian; `agent.retrieve_context` chỉ khoảng 20 ms)
- Dòng log tương ứng (`docker compose logs agent | grep <trace_id>`):

```json
⏳
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

> ⏳ Cần Docker. Lệnh ở CHECKPOINTS CP8 (có `-p k5-day14-observability`), hoặc chạy workflow `benchmark-production` trên GitHub Actions, tải artifact `locust-benchmark-results` về `benchmark-results/`, lấy dòng **Aggregated** trong `scale_1_stats.csv` / `scale_3_stats.csv`.

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | ⏳ | ⏳ | ⏳ | ⏳ | ⏳ |
| 3 | ⏳ | ⏳ | ⏳ | ⏳ | ⏳ |

**Giải thích kết quả:** *(điền theo số đo. Khung phân tích:)* mỗi agent container bị giới hạn `cpus: 0.5`. Với 1 instance, 100 users dễ làm bão hoà CPU, request xếp hàng và p95 tăng. Lên 3 instance, RPS tăng và p95 giảm nếu nút thắt là CPU của agent. Nếu p95 **gần như không đổi** thì nút thắt nằm ở **LLM latency** (panel LLM p95 khoảng 150–230 ms cộng 3% request chậm 1.5s). Scale ngang không làm từng LLM call nhanh hơn, chỉ tăng số call song song. Kết quả ở mục 2.1 (develop, 1 process) cho thấy throughput dừng ở khoảng 50 RPS do bão hoà CPU, nên dự đoán scale 3 instance sẽ tăng RPS rõ rệt.

---

## 6. Kết luận

- 3 điều học được về benchmark & observability:
  1. **Average nói dối.** 3% request chậm chỉ làm avg tăng 17% nhưng làm p99 tăng ×3. SLO phải đặt theo percentile và đo bằng load test đủ mẫu (300+ request), không đo bằng 23 câu eval.
  2. **"Nhanh" và "đúng" là 2 benchmark khác nhau.** Metric hạ tầng xanh hết vẫn có thể đang trả lời sai (thí nghiệm E). Eval golden dataset + quality gate trong CI là lớp bảo vệ bắt buộc, và nên so sánh theo **cost / câu đúng** chứ không theo cost / request.
  3. **Tăng concurrency không tăng throughput mãi.** Theo định luật Little, khi một tài nguyên (CPU event loop, LLM rate limit) bão hoà thì tăng tải chỉ làm tăng hàng đợi và latency. Phải tìm nút thắt bằng metric và trace rồi mới scale đúng chỗ.
- Nếu đưa agent này lên production thật, mình sẽ thêm:
  - **Metric:** `agent_question_length_chars` (đã thêm, Exercise 7.1), tỉ lệ 429/402 theo thời gian (rate limit/budget có chặn nhầm user thật không), Redis latency/errors, token/request theo version, time-to-first-token nếu streaming, saturation của LLM provider (429 từ upstream).
  - **Alert:** burn-rate SLO đa cửa sổ (1h/6h) thay cho ngưỡng tĩnh, `AgentReadinessFailing` (`/ready` 503 kéo dài), budget đã dùng > 80% trong ngày, retrieval hit ratio < ngưỡng, synthetic golden-check fail, và giám sát tầng Nginx (5xx/504 từ LB, vì lỗi 504 không hiện trong metric của agent).

---

## 7. Trả lời câu hỏi Exercise 7.1 – 7.6

### Exercise 7.1 — metrics

1. **Counter / Gauge / Histogram** (trích `reports/metrics_snapshot_v2.txt`, agent v2 sau 23 câu eval):
   - Counter: `http_requests_total{method="POST",route="/ask",status="200"} 23.0`, `llm_tokens_total{model="mock-llm-small",type="input"} 1729.0`, `llm_cost_usd_total{model="mock-llm-small"} 0.00079035` (chỉ tăng, dùng với `rate()`).
   - Gauge: `agent_in_flight_requests 0.0` (lên xuống theo số request đang xử lý), `agent_info{model="mock-llm-small",version="v2"} 1.0`.
   - Histogram: `http_request_duration_seconds_bucket{le="0.2",method="POST",route="/ask"}`, kèm `_sum` và `_count`. Prometheus tính percentile bằng `histogram_quantile()`.
2. **Dùng `request.url.path` làm label thì sao?** Mỗi URL lạ (`/wp-admin`, `/.env`, `/a1b2c3`…) tạo ra một time series mới cho mỗi metric, nhân với mọi tổ hợp `method` × `status` × số bucket histogram. Bot quét vài nghìn URL là có hàng chục nghìn series, khiến Prometheus tốn RAM, query chậm, thậm chí OOM (tấn công cardinality). Dùng `route.path` (template) thì mọi URL không khớp gom về 1 label `unmatched`. Đã thử thực tế: `GET /wp-admin` → 404 chỉ tạo `http_requests_total{method="GET",route="unmatched",status="404"} 1.0`.
3. **Metric mới** `agent_question_length_chars` (Histogram, buckets 20…2000) trong `develop/app.py`. Sau eval: `agent_question_length_chars_count 23.0`. Dùng Histogram chứ không dùng label `length=...` vì độ dài có vô số giá trị, làm label sẽ bùng nổ cardinality.

### Exercise 7.2 — Vì sao avg chỉ tăng nhẹ còn p99 tăng vọt? SLO theo chỉ số nào?
Average chia đều vài request chậm cho toàn bộ mẫu: 3% × 1.5s ≈ +45 ms (đo được +40 ms: 231 → 271). Còn p99 **chính là** nhóm 1% chậm nhất, nên khi > 1% request chậm thì p99 = latency của request chậm (589 → 1735 ms). SLO đặt theo **p95/p99** vì nó mô tả trải nghiệm của nhóm user tệ nhất mà average che mất.

### Exercise 7.4 — Observability stack
1. **p95 và avg là bao nhiêu, khoảng cách nói gì?** ⏳ số đọc từ Grafana: p95 = ___ ms, avg = ___ ms. Giải thích: p95 cao hơn avg rõ rệt nghĩa là phân bố latency lệch phải (tail latency). Phần lớn request nhanh, nhưng khoảng 3% request bị LLM chậm thêm 1.5s kéo đuôi phân bố. Avg trông ổn nhưng 5% user vẫn chờ lâu.
2. **Nginx có chia đều cho 2 instance không?** ⏳ đọc panel "Requests/s theo instance". Kỳ vọng gần bằng nhau vì upstream round-robin qua Docker DNS. Lệch nhẹ là bình thường do keepalive connection và thời gian xử lý khác nhau.
3. **Vì sao input tokens/s > output tokens/s?** Agent v2 nhét system prompt + tài liệu retrieve được + câu hỏi vào prompt, còn câu trả lời ngắn. Số đo thật ở develop: input 1729 vs output 885 token cho 23 câu (khoảng 2:1).
4. **`curl http://localhost:8080/metrics` trả gì?** 404, vì `nginx.conf` chặn `/metrics` ở cổng public. `/metrics` lộ thông tin nội bộ (traffic, cost, version) và có thể bị spam. Prometheus scrape trực tiếp từng container qua mạng nội bộ Docker (`dns_sd_configs`), không đi qua Nginx.

### Exercise 7.5 — Tracing
⏳ Điền ở mục 4.3 sau khi chạy stack. Kỳ vọng span `chat mock-llm-small` chiếm phần lớn thời gian của trace chậm. Trace lỗi có tag `error=true` và event `exception` "Upstream LLM error: 503".

### Exercise 7.6 — Đổi `AGENT_VERSION=v1` không alert nào firing, phát hiện bằng cách nào?
Xem phần trả lời thí nghiệm E ở mục 4.2: eval golden dataset trong CI (quality gate), alert trên metric "proxy" chất lượng (retrieval hit ratio, input token/request), online eval trên mẫu traffic thật và feedback người dùng, synthetic check định kỳ. Unit test alert rules (`promtool test rules`): ⏳ chạy lệnh trong Exercise 7.6 và dán kết quả `SUCCESS`.
