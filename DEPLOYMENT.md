# Deployment Information

> Service deploy là **agent Part 6** trong thư mục `06-lab-complete/`.

## Public URL
https://production-ai-agent-jt3z.onrender.com

## Platform
Render, gói Free. Deploy bằng Blueprint `06-lab-complete/render.yaml`: web service Docker (`rootDir: 06-lab-complete`) + Render Key Value (Redis-compatible), cả hai cùng region, nối qua mạng nội bộ.

> Free web service tự tắt sau 15 phút không có request. Request đầu tiên sau đó mất khoảng 1 phút để khởi động lại, nên trước khi kiểm tra hãy mở `/health` một lần cho service "thức dậy".

## Test Commands

### Tự kiểm CP6 (chỉ in mã HTTP, chụp ảnh không lộ key)
```bash
BASE=https://production-ai-agent-jt3z.onrender.com
curl -sS -o /dev/null -w '%{http_code}
' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}
' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}
' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}
' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```
Kết quả đo ngày 2026-11-25:

```text
health 200          {"status":"ok","environment":"production","uptime_seconds":119.3,"pid":28}
ready 200           {"status":"ready","redis":"ok"}          ← agent đã kết nối Render Key Value
ask-no-key 401      {"detail":"Invalid or missing API key. Send header X-API-Key."}
ask-wrong-key 401
ask-with-key 200    (X-API-Key = AGENT_API_KEY do Render sinh, chạy từ PowerShell, chỉ in mã HTTP)
```

### Health Check
```bash
curl https://production-ai-agent-jt3z.onrender.com/health
# Expected: {"status": "ok", ...}
```

### Readiness (Redis)
```bash
curl https://production-ai-agent-jt3z.onrender.com/ready
# Expected: {"status": "ready", "redis": "ok"}
```

### Authentication required
```bash
curl -X POST https://production-ai-agent-jt3z.onrender.com/ask \
  -H "Content-Type: application/json" -d '{"question": "Hello"}'
# Expected: 401
```

### API Test (with authentication)
```bash
curl -X POST https://production-ai-agent-jt3z.onrender.com/ask \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
# Expected: 200 {"question": "Hello", "answer": "...", "usage": {...}}
```

### Rate limiting (10 req/phút)
```bash
for i in $(seq 1 15); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST https://production-ai-agent-jt3z.onrender.com/ask \
    -H "X-API-Key: YOUR_KEY" -H "Content-Type: application/json" \
    -d '{"user_id":"test","question":"test"}'
done
# Expected: 10 × 200, sau đó 429
```

### Grader against public URL
```bash
cd 06-lab-complete
python check_production_ready.py --public-url https://production-ai-agent-jt3z.onrender.com
```

## Environment Variables Set
- `PORT` (Render tự cấp, Dockerfile dùng `${PORT:-8000}`)
- `REDIS_URL` (Blueprint tự lấy `connectionString` của Key Value `agent-redis`)
- `AGENT_API_KEY` (Render tự sinh bằng `generateValue: true`; xem giá trị ở Dashboard → service → Environment)
- `ENVIRONMENT=production`
- `RATE_LIMIT_PER_MINUTE=10`
- `DAILY_BUDGET_USD=1.0`, `MONTHLY_BUDGET_USD=10.0`

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
