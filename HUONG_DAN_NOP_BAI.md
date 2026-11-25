# Hướng dẫn nộp bài — Day 14 (K5, cá nhân)

> Tổng hợp từ `README.md` (mục *Lưu ý khi làm bài K5*), `SUBMISSION.md`, `RULES.md`, `RUBRIC.md`, `CHECKPOINTS.md`.
> **Nộp:** link repo GitHub trên LMS, **không nộp zip**. **Deadline:** 23h59 (GMT+7) ngày lab, trừ khi Lab Coach báo khác. Bản được chấm là commit cuối trước deadline.

## 1. Mục đích, mục tiêu, output

- **Mục đích:** đưa AI agent từ "chạy được trên laptop" thành dịch vụ production: Docker, deploy cloud có URL public, bảo mật (API key, rate limit, cost guard), stateless để scale. Sau đó đo nó (load test, eval) và giám sát nó (Prometheus, Grafana, Jaeger, alert).
- **Mục tiêu:** đạt `PASS 12/12` với `check_production_ready.py`, có URL public trả 200/200/401/200, có benchmark báo cáo bằng số thật. **Đạt môn: 70/100** (84/120 điểm thô).
- **Output:** repo `K5-L3A-DAY14-HoVaTen-MSSV-Deployment-Benchmark-Observability` (Public) với cấu trúc:

```text
<repo>/
├── MISSION_ANSWERS.md       ✅ đã viết (còn vài ô ⏳ cần Docker/cloud)
├── DEPLOYMENT.md            ⏳ điền URL
├── BENCHMARK_REPORT.md      ✅ mục 1–3, 6, 7 · ⏳ mục 4–5 (Docker)
├── reports/                 ✅ 7 file load + 3 file eval (đúng tên SUBMISSION.md)
├── benchmark-results/       ⏳ scale_1_stats.csv, scale_3_stats.csv
├── screenshots/             ⏳ 7 ảnh
├── evidence/                ✅ output chạy thật Part 1/4/5/6 (thêm, không bắt buộc)
├── .github/workflows/       ✅ production-ready, quality-gate, benchmark-production
└── 06-lab-complete/         ✅ code Part 6 (làm ngay trong thư mục này)
```

Thang điểm: Part 1–5 mỗi phần 8đ · Part 6: 60đ (mục ⚠️ cũng tính 0đ) · Part 7: 20đ. Trừ điểm: commit `.env`/secret −10, sai tên repo hoặc sai chỗ file −5, repo private thì không chấm, số trong report không khớp JSON/CSV thì mục đó 0đ.

## 2. Tạo bản fork và đưa bài lên (bắt buộc làm trước)

1. Mở repo đề bài trên GitHub (`VinUni-AI20k/K5-L3-Day14-...`), bấm **Fork**.
2. Trong bản fork: **Settings → Repository name** → `K5-L3A-DAY14-HoVaTen-MSSV-Deployment-Benchmark-Observability`. Họ tên viết liền, không dấu, viết hoa chữ cái đầu, vd `NguyenVanA`. Để repo **Public**.
3. Gắn thư mục bài làm trên máy vào bản fork (giữ lịch sử commit của đề, bài làm thành các commit mới):

```powershell
cd "D:\Admin\K5-L3-Day14-Deployment-Agent-Benchmark-Observability-main\K5-L3-Day14-Deployment-Agent-Benchmark-Observability-main"
```

```powershell
git init; git remote add origin https://github.com/<username>/K5-L3A-DAY14-HoVaTen-MSSV-Deployment-Benchmark-Observability.git; git fetch origin
```

```powershell
git reset origin/main; git status
```

`git reset` (không `--hard`) chỉ trỏ nhánh về commit của fork, **không đụng file trên máy**. `git status` phải chỉ hiện những file đã sửa/thêm, không có `.env` hay `.venv`. Nếu nhánh mặc định tên khác `main` thì đổi cho đúng.

4. Commit theo từng phần cho lịch sử rõ ràng, rồi push:

```powershell
git add 06-lab-complete/app 06-lab-complete/utils 06-lab-complete/Dockerfile 06-lab-complete/.dockerignore 06-lab-complete/docker-compose.yml 06-lab-complete/docker-compose.scale.yml 06-lab-complete/nginx 06-lab-complete/.env.example 06-lab-complete/railway.toml 06-lab-complete/render.yaml 06-lab-complete/README.md; git commit -m "Part 6: production-ready agent (auth, Redis rate limit + cost guard, health/ready, JSON logs, multi-stage Docker)"
```

```powershell
git add 06-lab-complete/benchmark-observability reports; git commit -m "Part 7: question-length metric, fix knowledge base (v2 23/23), load test + eval reports"
```

```powershell
git add -A; git commit -m "Docs: mission answers, benchmark report, deployment, CI workflows"; git push -u origin main
```

5. Kiểm tra: mở link repo ở cửa sổ ẩn danh, không bị 404. Chạy `git log --all --oneline -- '*.env' '.env'` không in gì.

## 3. Lấy `PASS 12/12` (60 điểm Part 6)

Python Windows **không bao giờ** đạt 12/12 (không gửi được SIGTERM). Chọn 1 trong 2 cách:
- **WSL2 + Docker Desktop** (cách lớp hướng dẫn): `wsl --install`, bật WSL integration trong Docker Desktop. Trong terminal WSL: `python -c "import os; print(os.name)"` phải in `posix`. Sau đó `cd 06-lab-complete && pip install -r requirements.txt && python check_production_ready.py`.
- **GitHub Actions:** sau khi push, tab **Actions → production-ready** chạy script chấm đầy đủ trên Linux có Docker.

Dán phần `📋 Checklist Deliverable` (PASS 12/12) vào cuối mục Part 6 của `MISSION_ANSWERS.md`, thay khối 10/12 hiện tại.

## 4. Deploy (Part 3 + nhóm Deployment Part 6)

Deploy **agent Part 6** (`06-lab-complete/`), không deploy app mẫu.

**Railway (khuyên dùng):** railway.app → New Project → Deploy from GitHub repo → chọn bản fork → vào service → **Settings → Root Directory = `06-lab-complete`** (để Railway dùng `railway.toml` + `Dockerfile` của bài). Sau đó:
- **+ New → Database → Redis**.
- Variables của agent: `AGENT_API_KEY` (key ngẫu nhiên), `REDIS_URL=${{Redis.REDIS_URL}}`, `ENVIRONMENT=production`, `RATE_LIMIT_PER_MINUTE=10`, `DAILY_BUDGET_USD=1.0`, `MONTHLY_BUDGET_USD=10.0`.
- **Settings → Networking → Generate Domain**.

Kiểm `/ready` trả 200, chạy 4 lệnh CP6 trong `DEPLOYMENT.md` (kết quả 200/200/401/200), chụp `screenshots/dashboard.png`, `running.png`, `test.png`. Điền URL vào `DEPLOYMENT.md` và mục Part 3 của `MISSION_ANSWERS.md`.

(Render: New → Blueprint, Blueprint path `06-lab-complete/render.yaml`. File đã khai báo web + Redis và `generateValue` cho key.)

## 5. Các ô ⏳ còn lại cần Docker (làm trong WSL2)

| Ô ⏳ | Lệnh |
|---|---|
| Part 1.2 gọi bản develop | `cd 01-localhost-vs-production/develop && python app.py`, rồi `curl -X POST "http://localhost:8000/ask?question=Hello"` |
| Part 2 size image + container + Nginx | Từ **gốc repo**: `docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .`, `docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .`, `docker images \| grep my-agent`; stack: `cd 02-docker/production && touch .env.local && docker compose up -d --build` |
| Part 5.5 | `cd 05-scaling-reliability/production && touch .env.local && docker compose -p k5-day14-scaling up -d --build --scale agent=3 && python test_stateless.py`, xong thì `docker compose -p k5-day14-scaling down` |
| Part 7 mục 4–5, 7.4–7.6 | CHECKPOINTS CP8: `cd 06-lab-complete/benchmark-observability/production && docker compose -p k5-day14-observability up -d --build --scale agent=1` … Locust headless scale 1 và 3, chụp 4 ảnh (ảnh alert phải thấy **≥ 2 alert cùng firing**), ghi `trace_id` + dòng log JSON. Cuối cùng copy CSV: `cp -r 06-lab-complete/benchmark-observability/production/benchmark-results/. benchmark-results/` |

Không có máy chạy Docker thì: workflow **benchmark-production** (Actions → Run workflow) cho CSV Locust + kết quả promtool. RUBRIC còn cho tối đa 50% phần Observability nếu chạy `production/app` bằng Python và giải thích `/metrics`.

## 6. Trước khi nộp

- [ ] Đọc lại và tự sửa câu trả lời theo hiểu biết của mình (Lab Coach có thể hỏi giải thích bất kỳ dòng code hay con số nào). Bổ sung **AI log** cuối `MISSION_ANSWERS.md` nếu dùng AI thêm.
- [ ] Không còn ô ⏳. Mọi số khớp JSON/CSV (`reports/` và `06-lab-complete/benchmark-observability/develop/reports/` giống nhau).
- [ ] Họ tên chỉ ở tên repo và ô "Họ tên" của `BENCHMARK_REPORT.md`. Không có email, số điện thoại.
- [ ] Không sửa `check_production_ready.py` và `golden_dataset.jsonl` (đã giữ nguyên).
- [ ] `git push`, rồi nộp link repo trên LMS.
- [ ] Sau khi được chấm: `docker compose ... down -v`, có thể xoá service cloud.

## 7. Chạy lại phần local trên máy này (Windows)

Virtualenv `.venv` ở gốc thư mục (đã nằm trong `.gitignore`). Trên Windows nhớ đặt `PYTHONUTF8=1` để script ghi được file tiếng Việt:

```powershell
.\.venv\Scripts\Activate.ps1; $env:PYTHONUTF8="1"
```
