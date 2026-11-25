# Deployment Information

> ⏳ Điền URL thật sau khi deploy (xem `HUONG_DAN_NOP_BAI.md`, bước 4). Service deploy là **agent Part 6** trong thư mục `06-lab-complete/`.

## Public URL
https://<your-agent>.up.railway.app

## Platform
Railway (build bằng `Dockerfile`, cấu hình trong `railway.toml`). Phương án thay thế: Render Blueprint (`render.yaml`, gồm web service + Redis).

## Test Commands

### Tự kiểm CP6 (chỉ in mã HTTP, chụp ảnh không lộ key)
```bash
BASE=https://<your-agent>.up.railway.app
curl -sS -o /dev/null -w '%{http_code}
' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}
' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}
' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}
' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```
Kết quả: ⏳ `200 / 200 / 401 / 200`

### Health Check
```bash
curl https://<your-agent>.up.railway.app/health
# Expected: {"status": "ok", ...}
```

### Readiness (Redis)
```bash
curl https://<your-agent>.up.railway.app/ready
# Expected: {"status": "ready", "redis": "ok"}
```

### Authentication required
```bash
curl -X POST https://<your-agent>.up.railway.app/ask \
  -H "Content-Type: application/json" -d '{"question": "Hello"}'
# Expected: 401
```

### API Test (with authentication)
```bash
curl -X POST https://<your-agent>.up.railway.app/ask \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
# Expected: 200 {"question": "Hello", "answer": "...", "usage": {...}}
```

### Rate limiting (10 req/phút)
```bash
for i in $(seq 1 15); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST https://<your-agent>.up.railway.app/ask \
    -H "X-API-Key: YOUR_KEY" -H "Content-Type: application/json" \
    -d '{"user_id":"test","question":"test"}'
done
# Expected: 10 × 200, sau đó 429
```

### Grader against public URL
```bash
cd 06-lab-complete
python check_production_ready.py --public-url https://<your-agent>.up.railway.app
```

## Environment Variables Set
- `PORT` (Railway tự cấp)
- `REDIS_URL` (từ Redis plugin của Railway: `${{Redis.REDIS_URL}}`)
- `AGENT_API_KEY` (secret, sinh bằng `python -c "import secrets; print(secrets.token_urlsafe(32))"`)
- `ENVIRONMENT=production`
- `LOG_LEVEL=INFO`
- `RATE_LIMIT_PER_MINUTE=10`
- `DAILY_BUDGET_USD=1.0`, `MONTHLY_BUDGET_USD=10.0`

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
