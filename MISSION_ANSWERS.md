# Day 14 Lab - Mission Answers

> **Repo:** `K5-L3A-DAY14-NguyenKhoiNguyen-2A202603453-Deployment-Benchmark-Observability`
> **Ngày làm:** 2026-11-25
> **Môi trường chạy thử:** Windows 11, Intel i7-12650H (10 cores / 16 threads), 15.7 GB RAM, Python 3.11.9

Output gốc của các lần chạy thử nằm trong thư mục [`evidence/`](evidence/) và [`reports/`](reports/).

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found (`01-localhost-vs-production/develop/app.py`)

1. **Secret hard-code trong code**: `OPENAI_API_KEY = "sk-hardcoded-..."` và `DATABASE_URL` chứa mật khẩu `password123`. Push lên GitHub là lộ key ngay.
2. **Log ra secret**: `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")`. Khi chạy thử, log thật có dòng `[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this`.
3. **Dùng `print()` thay vì logging có cấu trúc**: không có level, không có timestamp, không parse được. Trên Windows, `print()` câu trả lời tiếng Việt còn làm app crash với `UnicodeEncodeError` (console cp1252), nên `POST /ask` trả **HTTP 500** (xem `evidence/part1_part4_test_output.txt`). Đây đúng là lỗi "works on my machine".
4. **Không có health check**: `GET /health` trả **404**, nên platform không biết lúc nào cần restart container.
5. **Host/port cố định**: `host="localhost"` khiến container không nhận được kết nối từ bên ngoài. `port=8000` thì bỏ qua biến `PORT` mà Railway/Render cấp.
6. **`reload=True` và `DEBUG = True`** bật cứng: chế độ dev chạy luôn ở production (tốn tài nguyên, lộ thông tin debug).
7. **Config không quản lý tập trung**: `MAX_TOKENS`, `DEBUG` là hằng số trong code, muốn đổi phải sửa code rồi build lại.
8. **Không xử lý shutdown**: không có lifespan hay SIGTERM handler, nên request đang chạy có thể bị cắt ngang khi deploy.
9. **Input qua query param, không validate**: `question: str` không giới hạn độ dài và không có model Pydantic.

### Exercise 1.2: Chạy bản develop

Bản develop nhận `question` qua **query string** (README K5 lưu ý 3). Gọi bằng `curl -X POST "http://localhost:8000/ask?question=Hello"`.
- Trên Python Windows: **HTTP 500**, do `print()` tiếng Việt gây `UnicodeEncodeError` (anti-pattern số 3 ở trên).
- ⏳ Chạy lại trong WSL2 và dán output 200 vào đây: `cd 01-localhost-vs-production/develop && pip install -r requirements.txt && python app.py`

```text
⏳ (dán output curl)
```

### Exercise 1.3: Comparison table

| Feature | Develop (basic) | Production (advanced) | Why Important? |
|---------|---------|------------|----------------|
| Config | Hard-code trong code (`DEBUG = True`, key, DB URL) | `config.py` đọc env var (`os.getenv`), có `validate()` báo lỗi sớm | Một image chạy được ở dev/staging/prod, đổi config không cần build lại, không lộ secret |
| Secrets | `sk-...` và password nằm trong code, còn bị in ra log | Lấy từ env / `.env` (đã nằm trong `.gitignore`), không bao giờ log | Tránh lộ key trên Git hoặc log aggregator |
| Health check | Không có (`/health` → 404) | `/health` (liveness) + `/ready` (readiness, 503 khi chưa sẵn sàng) | Platform tự restart khi chết, LB chỉ route tới instance đã sẵn sàng |
| Logging | `print()` | JSON qua `logging` (`{"time":..,"level":..,"msg":..}`) | Parse/lọc được trên Loki/Datadog, có level, không crash vì encoding |
| Shutdown | Đột ngột | Graceful: lifespan đặt `is_ready=False`, chờ request xong, SIGTERM handler | Deploy và scale down không làm mất request của user |
| Host / Port | `localhost:8000` cố định | `0.0.0.0` + `PORT` từ env | Chạy được trong container và trên cloud (PORT do platform cấp) |
| Reload/Debug | `reload=True` luôn bật | Chỉ bật khi `DEBUG=true` | Production không chạy file watcher, không lộ stack trace |
| CORS | Không cấu hình | `ALLOWED_ORIGINS` từ env | Kiểm soát được origin nào gọi API |

---

## Part 2: Docker

### Exercise 2.1: Dockerfile questions (`02-docker/develop/Dockerfile`)

1. **Base image:** `python:3.11`, bản Python đầy đủ (Debian + build tools), khoảng 1 GB.
2. **Working directory:** `/app` (`WORKDIR /app`).
3. **Vì sao COPY requirements.txt trước:** để tận dụng **layer cache**. Layer `pip install` chỉ build lại khi `requirements.txt` đổi. Sửa code (`COPY app.py`) chỉ build lại các layer sau đó nên build nhanh hơn nhiều.
4. **CMD vs ENTRYPOINT:** `ENTRYPOINT` là lệnh cố định của container. `CMD` là lệnh hoặc tham số mặc định, bị ghi đè được bằng `docker run image <cmd>`. Khi dùng cả hai thì CMD thành tham số cho ENTRYPOINT. Nên dùng exec form (`["python","app.py"]`) để process là PID 1 và nhận được SIGTERM.

### Exercise 2.2: Build và chạy container develop

```text
⏳ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .   (chạy từ gốc repo)
⏳ docker run -p 8000:8000 my-agent:develop
⏳ curl -X POST "http://localhost:8000/ask?question=What%20is%20Docker"   → dán output
```

### Exercise 2.3: Multi-stage build (`02-docker/production/Dockerfile`)

- **Stage 1 (builder):** `python:3.11-slim`, cài `gcc` và `libpq-dev`, rồi `pip install --user -r requirements.txt`. Stage này chỉ để build, không dùng để deploy.
- **Stage 2 (runtime):** `python:3.11-slim` sạch, tạo user non-root `appuser`, chỉ `COPY --from=builder /root/.local` (packages đã cài) và source code, có `HEALTHCHECK`, chạy `uvicorn ... --workers 2`.
- **Vì sao image nhỏ hơn:** image cuối không chứa gcc, header, apt cache, pip cache hay các layer trung gian. Base `slim` cũng nhỏ hơn base đầy đủ khoảng 900 MB.

**Image size comparison** *(máy làm bài chưa cài Docker. Chạy 2 lệnh dưới trên máy có Docker rồi điền số)*:

```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
docker images | grep my-agent
```

- Develop: `____` MB (base `python:3.11` thường khoảng 1.0–1.1 GB)
- Production: `____` MB (base `python:3.11-slim` thường khoảng 150–250 MB)
- Difference: `____` % (`(develop - production) / develop × 100`)

### Exercise 2.4: Docker Compose stack (`02-docker/production/docker-compose.yml`)

```
Client ──:80/:443──▶ nginx ──▶ agent (FastAPI, 2 workers) ──▶ redis  (cache/session)
                                              └──────────────▶ qdrant (vector DB)
              (tất cả nằm trong network bridge "internal"; chỉ nginx publish port ra ngoài)
```

- **Services:** `agent`, `redis`, `qdrant`, `nginx`.
- **Test qua Nginx** ⏳: `cd 02-docker/production && touch .env.local && docker compose up -d --build`, rồi `curl http://localhost/health` và `curl -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'` (bản production nhận JSON), dán output vào đây.
- **Giao tiếp:** qua Docker DNS trong network `internal` bằng tên service (`redis://redis:6379/0`, `http://qdrant:6333`). Agent dùng `depends_on: condition: service_healthy` nên chỉ start khi Redis/Qdrant đã healthy. Chỉ Nginx publish port ra host, còn agent, redis, qdrant không lộ ra ngoài.

---

## Part 3: Cloud Deployment

### Exercise 3.1: Railway deployment

Theo CHECKPOINTS CP6, lớp K5 deploy luôn **agent Part 6** (`06-lab-complete/`, dùng `railway.toml` / `render.yaml` của bài), không deploy app mẫu.

- URL: ⏳ `https://<your-agent>.up.railway.app` (chi tiết trong [`DEPLOYMENT.md`](DEPLOYMENT.md))
- Kết quả 4 lệnh tự kiểm CP6: ⏳ `/health` 200 · `/ready` 200 · `/ask` không key 401 · `/ask` có key 200
- Screenshot: `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png`

### Exercise 3.2: `render.yaml` vs `railway.toml`

| | `railway.toml` | `render.yaml` |
|---|---|---|
| Định dạng | TOML, cấu hình **1 service** | YAML Blueprint, khai báo **nhiều service** (web + redis) |
| Build | `builder = "NIXPACKS"` (tự nhận diện) hoặc `DOCKERFILE` | `runtime: python` + `buildCommand`, hoặc `runtime: docker` |
| Start | `startCommand = "uvicorn ... --port $PORT"` | `startCommand: uvicorn ... --port $PORT` |
| Health | `healthcheckPath`, `healthcheckTimeout` | `healthCheckPath` |
| Env / secrets | Đặt ngoài file (`railway variables set`, dashboard) | Khai báo trong file: `value`, `sync: false` (nhập tay), `generateValue: true` (Render tự sinh) |
| Hạ tầng phụ | Thêm Redis bằng plugin trên dashboard | Khai báo luôn `type: redis` trong cùng Blueprint (Infrastructure as Code) |
| Restart | `restartPolicyType = "ON_FAILURE"` | Render tự quản lý |

### Exercise 3.3: Cloud Run CI/CD (`cloudbuild.yaml` + `service.yaml`)

Pipeline Cloud Build có 4 bước nối tiếp nhau (`waitFor`):

1. **test**: `python:3.11-slim`, cài requirements và chạy `pytest tests/`. Test fail thì dừng luôn, không deploy.
2. **build**: `docker build`, gắn 2 tag `gcr.io/$PROJECT_ID/ai-agent:$COMMIT_SHA` và `:latest`, dùng `--cache-from` image `latest` để tái sử dụng layer.
3. **push**: `docker push --all-tags` lên Container Registry.
4. **deploy**: `gcloud run deploy` với image theo `COMMIT_SHA` (rollback được về đúng commit), region `asia-southeast1`, `--min-instances=1` để tránh cold start, `--max-instances=10`, 512Mi/1 CPU, `--set-secrets=OPENAI_API_KEY=openai-key:latest` lấy từ Secret Manager.

`service.yaml` (Knative) khai báo cùng cấu hình theo kiểu IaC: autoscale `minScale 1` / `maxScale 10`, `containerConcurrency: 80`, CPU/RAM limits, secret qua `secretKeyRef`, `livenessProbe` → `/health` và `startupProbe` → `/ready`.

---

## Part 4: API Security

### Exercise 4.1: API Key authentication (`04-api-gateway/develop/app.py`)

- **Check ở đâu:** dependency `verify_api_key()` dùng `APIKeyHeader(name="X-API-Key", auto_error=False)`, được inject vào `/ask` bằng `Depends(verify_api_key)`.
- **Sai key thì sao:** thiếu key trả **401**, sai key trả **403** "Invalid API key." (Final project trả 401 cho cả 2 trường hợp, đúng theo hợp đồng của script chấm.)
- **Rotate key:** key đọc từ env `AGENT_API_KEY`, nên chỉ cần đổi biến môi trường rồi restart hoặc redeploy, không phải sửa code. Muốn rotate không downtime thì cho phép tạm thời 2 key (cũ + mới), thông báo client chuyển sang key mới rồi gỡ key cũ.

### Exercise 4.1–4.3: Test results (chạy thật, trích từ `evidence/part1_part4_test_output.txt`)

```text
# 4.1 — API key
POST /ask (không có key)        → HTTP 401 {"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
POST /ask (sai key)             → HTTP 403 {"detail":"Invalid API key."}
POST /ask (key secret-key-123)  → HTTP 200 {"question":"Hello","answer":"Agent đang hoạt động tốt! ..."}

# 4.2 — JWT (04-api-gateway/production)
POST /auth/token admin/secret   → HTTP 401 {"detail":"Invalid credentials"}   ← tài khoản trong CODE_LAB không tồn tại
POST /auth/token student/demo123→ HTTP 200 {"access_token":"eyJhbGciOiJIUzI1NiIs...","token_type":"bearer",...}
POST /ask không token           → HTTP 401 "Authentication required. Include: Authorization: Bearer <token>"
POST /ask token giả             → HTTP 403 "Invalid token."
POST /ask với token             → HTTP 200 {..., "usage":{"requests_remaining":9, ...}}

# 4.3 — Rate limit (student = 10 req/phút, đã dùng 1 ở trên)
request  1..9  → HTTP 200 (remaining 8 → 0)
request 10..20 → HTTP 429 Retry-After=59
teacher (admin, 100 req/phút): 15/15 request thành công
```

> Ghi chú: endpoint lấy token là **`POST /auth/token`** (không phải `/token`). Tài khoản demo là `student/demo123` và `teacher/teach456`. `admin/secret` như trong CODE_LAB không tồn tại.

**JWT flow (`auth.py`):** login → `create_token()` ký HS256 payload `{sub, role, iat, exp(+60 phút)}` bằng `JWT_SECRET` → client gửi `Authorization: Bearer <token>` → `verify_token()` dùng `jwt.decode` kiểm tra chữ ký và hạn → lấy `username`, `role`, không cần tra DB. Token hết hạn trả 401, token sai chữ ký trả 403.

**Rate limiter (`rate_limiter.py`):**
- **Algorithm:** Sliding Window (log): mỗi user có 1 `deque` timestamp, bỏ timestamp cũ hơn 60s rồi đếm.
- **Limit:** user **10 req/phút**, admin **100 req/phút**.
- **Bypass cho admin:** `app.py` chọn `rate_limiter_admin if role == "admin" else rate_limiter_user`. Admin không bypass hẳn mà dùng limiter riêng với giới hạn cao hơn.
- **Hạn chế:** state nằm trong memory nên mỗi worker/instance đếm riêng và mất khi restart. Final project đã chuyển sang Redis.

### Exercise 4.4: Cost guard implementation

Bản tham khảo (`04-api-gateway/production/cost_guard.py`) lưu in-memory: $1/ngày mỗi user (vượt thì **402**), $10/ngày toàn hệ thống (vượt thì 503), cảnh báo khi dùng tới 80%.

Cách implement trong final project ([`06-lab-complete/app/cost_guard.py`](06-lab-complete/app/cost_guard.py)):

- Chi phí mỗi request = `input_tokens/1000 × $0.00015 + output_tokens/1000 × $0.0006` (giá gpt-4o-mini).
- **Lưu trong Redis** (dùng chung cho mọi worker/instance): `INCRBYFLOAT cost:daily:YYYY-MM-DD` và `cost:monthly:YYYY-MM` trong một `MULTI/EXEC`.
- **Reset tự động:** key theo ngày có `EXPIRE` 2 ngày, key theo tháng `EXPIRE` 32 ngày. Sang ngày hoặc tháng mới thì key mới bắt đầu từ 0, không cần cron.
- `check_budget()` chạy **trước** khi gọi LLM: tổng ≥ `DAILY_BUDGET_USD` hoặc ≥ `MONTHLY_BUDGET_USD` (mặc định **$10/tháng**) thì trả **HTTP 402**.
- `record_cost()` chạy **sau** khi gọi LLM. Nếu Redis lỗi lúc ghi thì vẫn trả câu trả lời cho user (không bắt user nhận lỗi sau khi đã tốn tiền gọi LLM). Redis lỗi lúc check thì trả 503 (fail closed).

Phiên bản theo đúng chữ ký trong CODE_LAB:

```python
def check_budget(user_id: str, estimated_cost: float) -> bool:
    month_key = datetime.now(timezone.utc).strftime("%Y-%m")
    key = f"budget:{user_id}:{month_key}"
    current = float(r.get(key) or 0)
    if current + estimated_cost > 10:
        return False
    r.incrbyfloat(key, estimated_cost)
    r.expire(key, 32 * 24 * 3600)
    return True
```

---

## Part 5: Scaling & Reliability

### Exercise 5.1–5.5: Implementation notes

**5.1 Health checks**
- `/health` (liveness): chỉ trả lời "process còn sống" kèm uptime, version, memory. **Không** phụ thuộc Redis, vì Redis chết thì restart agent cũng không giúp gì.
- `/ready` (readiness): trả 503 khi đang khởi động, đang tắt hoặc không kết nối được Redis, để LB ngừng route traffic tới instance đó mà không restart nó.
- Kết quả chạy thật (`evidence/part5_test_output.txt`): `GET /health → 200 {"status":"ok",...,"checks":{"memory":{"status":"ok",...}}}`, `GET /ready → 200 {"ready":true,"in_flight_requests":1}`.

**5.2 Graceful shutdown**
- Khi nhận SIGTERM, uvicorn ngừng nhận kết nối mới, chờ request in-flight xong rồi chạy phần shutdown của `lifespan` (đóng kết nối) và thoát với exit code 0.
- Bài học khi làm final project: **không** tự `signal.signal(SIGTERM, handler)` mà không gọi lại handler cũ. Nếu vậy uvicorn không bao giờ biết phải tắt và `docker stop` sẽ SIGKILL sau 10 giây (exit 137). Final project dùng `lifespan` và để uvicorn xử lý signal. Trong Dockerfile dùng `exec uvicorn` để uvicorn là PID 1 và nhận SIGTERM trực tiếp, kèm `--timeout-graceful-shutdown 8` để tắt xong trước mốc 10 giây của `docker stop`.

**5.3 Stateless design**
- Anti-pattern: `conversation_history = {}` trong memory. Có N instance thì có N bản history khác nhau, restart là mất.
- Final project lưu history ở Redis (`RPUSH history:{user_id}` + `LTRIM` giữ 20 tin + `EXPIRE` 7 ngày), xem qua `GET /history/{user_id}`. Rate limit và cost cũng nằm trong Redis.

**5.4 Load balancing**: Nginx `upstream` trỏ tới service `agent`. Docker DNS trả về IP của mọi replica, Nginx chia round-robin, `proxy_next_upstream error timeout http_503` chuyển request sang instance khác khi một instance lỗi. Final project có thêm `06-lab-complete/docker-compose.scale.yml` + `06-lab-complete/nginx/nginx.conf` (phần mở rộng, không tính điểm):

```bash
cd 06-lab-complete
docker compose -f docker-compose.yml -f docker-compose.scale.yml up --build --scale agent=3
```

**5.5 Test stateless** *(⏳ cần chạy lại bằng Docker theo README K5 lưu ý 7: `cd 05-scaling-reliability/production && touch .env.local && docker compose -p k5-day14-scaling up -d --build --scale agent=3 && python test_stateless.py`, rồi dán output vào đây)*. Trước đó, khi máy chưa có Docker, đã mô phỏng bằng 2 instance (`:8051`, `:8052`) dùng chung 1 Redis và gửi request luân phiên:

```text
request 1 → :8051 served_by=instance-8051 storage=redis turn=2
request 2 → :8052 served_by=instance-8052 storage=redis turn=3
request 3 → :8051 served_by=instance-8051 storage=redis turn=4
request 4 → :8052 served_by=instance-8052 storage=redis turn=5
request 5 → :8051 served_by=instance-8051 storage=redis turn=6
History đọc từ instance khác: 10 messages
sau khi kill :8051 → served_by=instance-8052, history còn 12 messages ✅ (state không mất)
```

Hai instance khác nhau cùng đọc và ghi một session. Kill một instance thì conversation vẫn còn, vì state nằm ở Redis chứ không nằm trong process.

---

## Part 6: Final Project — kết quả `check_production_ready.py`

### 📋 Checklist Deliverable

Chạy trên Windows (không có Docker, Windows không gửi được SIGTERM) bằng `--skip-docker`: **38/38 checks passed**, 10/12 tiêu chí ✅. 2 tiêu chí còn lại ⚠️ (chưa kiểm tra được, chứ không phải ❌) vì cần Docker/Linux. Output đầy đủ: [`evidence/check_production_ready_windows_skip-docker.txt`](evidence/check_production_ready_windows_skip-docker.txt).

```text
  📋 Checklist Deliverable
     ⚠️  Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ⚠️  Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
  Result: 10/12 tiêu chí đạt · 38/38 checks passed
```

> **TODO trước khi nộp:** trong **WSL2** + Docker Desktop, `cd 06-lab-complete && python check_production_ready.py` (README K5 lưu ý 2: Python Windows không bao giờ đạt 12/12), **hoặc** xem log workflow GitHub Actions `production-ready` (Linux có Docker). Sau đó dán phần "📋 Checklist Deliverable" với kết quả `PASS 12/12` thay cho khối trên.


---

## AI log

> Theo RULES.md mục 1. Bài làm này được thực hiện cùng trợ lý AI **Claude Code** (Anthropic). Ghi lại trung thực những gì AI làm và những gì đã kiểm tra.

| # | Hỏi / giao việc cho AI | AI trả về / làm gì | Đã tự sửa và kiểm tra thế nào |
|---|---|---|---|
| 1 | Đọc toàn bộ repo (CODE_LAB, checklist, script chấm, skeleton 06) và giải thích yêu cầu | Tóm tắt 12 tiêu chí, "hợp đồng" của `check_production_ready.py`, các TODO | Đối chiếu với mục *Script chấm dựa vào…* trong `06-lab-complete/README.md` |
| 2 | Viết code Part 6 (`config.py`, `auth.py`, `redis_client.py`, `rate_limiter.py`, `cost_guard.py`, `main.py`) | Code dùng Redis sorted set (MULTI/EXEC) cho rate limit, `INCRBYFLOAT` theo ngày/tháng cho cost guard, `JsonFormatter`, lifespan | Chạy `check_production_ready.py --skip-docker`: 38/38 checks ✅. Gọi tay `/ask`, `/history`, 401 thiếu key. Lưu ý AI nêu: tự đăng ký SIGTERM handler sẽ làm uvicorn không tắt, nên chỉ dùng lifespan |
| 3 | Viết Dockerfile multi-stage, `.dockerignore`, compose, `.env.example`, `railway.toml`, `render.yaml` | Builder tạo venv `/opt/venv`, runtime slim + user non-root + HEALTHCHECK bằng urllib, `exec uvicorn` để làm PID 1 | Chạy thử lệnh HEALTHCHECK ngoài Docker. ⏳ Build image + `docker stop` cần kiểm bằng bản chấm đầy đủ (WSL2/Docker) |
| 4 | Không có Docker/Redis trên Windows: chạy script chấm thế nào? | Dùng `fakeredis` TCP server tạm thời + script bọc thay hàm ping (script chấm **không bị sửa**) | Chỉ dùng để thử local. Kết quả chính thức phải từ bản chạy đầy đủ |
| 5 | Chạy Part 1, 4, 5 và thu output | Chạy các app mẫu, ghi output vào `evidence/` | Phát hiện bản develop Part 1 lỗi 500 trên Windows (`print` tiếng Việt), `/auth/token` dùng `student/demo123`. Đã che token JWT |
| 6 | Chạy Part 7 Bước 1 (load test, MOCK_SLOW_RATE, eval) | Chạy lệnh như CP7, lưu `reports/*.json`. Thêm 2 entry HPA/JWT vào `KNOWLEDGE_BASE`, thêm metric `agent_question_length_chars` | Eval cuối 23/23, 0 regression. Mọi số trong `BENCHMARK_REPORT.md` lấy từ file JSON |
| 7 | Viết nháp `MISSION_ANSWERS.md`, `BENCHMARK_REPORT.md`, `DEPLOYMENT.md`, workflow CI | Nháp câu trả lời + phân tích | ⏳ Tự đọc lại, sửa theo hiểu biết của mình; điền các mục cần Docker/cloud bằng số tự đo |
