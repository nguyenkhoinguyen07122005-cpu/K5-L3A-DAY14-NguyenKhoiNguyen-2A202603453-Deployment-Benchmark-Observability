"""
Production AI Agent — Part 6 Final Project

  GET  /health   liveness  — luôn 200 khi process còn chạy (không phụ thuộc Redis)
  GET  /ready    readiness — 200 khi Redis OK, 503 khi Redis không kết nối được
  POST /ask      X-API-Key → rate limit (Redis) → cost guard (Redis) → LLM → ghi cost
  GET  /history/{user_id}   conversation history (lưu Redis, stateless)

Chạy:  uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2
Kiểm tra: python check_production_ready.py
"""
import json
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_tokens, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask


# ─────────────────────────────────────────────────────────
# Structured logging — mỗi dòng log là 1 JSON object
# ─────────────────────────────────────────────────────────
class JsonFormatter(logging.Formatter):
    RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "pid": record.process,
        }
        # Các field truyền qua logger.info(..., extra={...})
        for key, value in vars(record).items():
            if key not in self.RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _setup_logging() -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    log = logging.getLogger("agent")
    log.handlers = [handler]
    log.setLevel(settings.log_level)
    log.propagate = False
    return log


logger = _setup_logging()


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"event": event, **fields})


# ─────────────────────────────────────────────────────────
# Lifespan — startup / graceful shutdown
#   uvicorn tự xử lý SIGTERM: ngừng nhận kết nối mới, chờ request in-flight
#   xong rồi mới chạy phần shutdown dưới đây và thoát với exit code 0.
#   (Không tự đăng ký signal handler để không chặn mất handler của uvicorn.)
# ─────────────────────────────────────────────────────────
STATE = {"ready": False, "in_flight": 0, "started_at": time.time()}


@asynccontextmanager
async def lifespan(_: FastAPI):
    log_event("startup", environment=settings.environment, port=settings.port,
              rate_limit_per_minute=settings.rate_limit_per_minute,
              daily_budget_usd=settings.daily_budget_usd,
              redis_ok=redis_healthy(), api_key_configured=bool(settings.agent_api_key))
    if not settings.agent_api_key:
        log_event("config_warning", logging.WARNING,
                  detail="AGENT_API_KEY is empty: every /ask request will be rejected with 401")
    STATE["ready"] = True
    yield
    # ── graceful shutdown ──
    STATE["ready"] = False
    log_event("shutdown", in_flight=STATE["in_flight"])
    try:
        r.close()
    except Exception:  # noqa: BLE001 — đang tắt, lỗi đóng kết nối không quan trọng
        pass
    log_event("shutdown_complete")


app = FastAPI(title="Production AI Agent", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def access_log(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    start = time.perf_counter()
    STATE["in_flight"] += 1
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        STATE["in_flight"] -= 1
        log_event("request", request_id=request_id, method=request.method,
                  path=request.url.path, status=status,
                  ms=round((time.perf_counter() - start) * 1000, 1))


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    log_event("unhandled_error", logging.ERROR, path=request.url.path, error=repr(exc))
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ─────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str = Field("anonymous", min_length=1, max_length=64)


@app.get("/")
def root():
    return {"service": "production-ai-agent", "docs": "/docs",
            "endpoints": ["/health", "/ready", "POST /ask", "/history/{user_id}"]}


@app.get("/health")
def health():
    """Liveness — chỉ cần process còn chạy. Không kiểm tra Redis."""
    return {"status": "ok", "environment": settings.environment,
            "uptime_seconds": round(time.time() - STATE["started_at"], 1),
            "pid": os.getpid()}


@app.get("/ready")
def ready():
    """Readiness — chỉ nhận traffic khi Redis (state dùng chung) kết nối được."""
    if not STATE["ready"]:
        raise HTTPException(status_code=503, detail="shutting down")
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="redis unavailable")
    return {"status": "ready", "redis": "ok"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)          # 429 khi vượt RATE_LIMIT_PER_MINUTE
    check_budget()                     # 402 khi hết DAILY/MONTHLY budget

    started = time.perf_counter()
    answer = llm_ask(body.question)
    llm_ms = round((time.perf_counter() - started) * 1000, 1)

    input_tokens = estimate_tokens(body.question)
    output_tokens = estimate_tokens(answer)
    cost = record_cost(input_tokens, output_tokens)

    _append_history(body.user_id, body.question, answer)
    log_event("llm_call", user_id=body.user_id, input_tokens=input_tokens,
              output_tokens=output_tokens, cost_usd=round(cost, 8), llm_ms=llm_ms)
    return {
        "question": body.question,
        "answer": answer,
        "user_id": body.user_id,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                  "cost_usd": round(cost, 8)},
    }


@app.get("/history/{user_id}")
def history(user_id: str, _: str = Depends(verify_api_key)):
    try:
        items = r.lrange(f"history:{user_id}", 0, -1)
    except redis.RedisError as exc:
        raise HTTPException(status_code=503, detail="redis unavailable") from exc
    return {"user_id": user_id, "messages": [json.loads(i) for i in items]}


def _append_history(user_id: str, question: str, answer: str) -> None:
    """Conversation history nằm trong Redis → instance nào phục vụ cũng thấy như nhau."""
    key = f"history:{user_id}"
    now = datetime.now(timezone.utc).isoformat()
    try:
        pipe = r.pipeline(transaction=True)
        pipe.rpush(key, json.dumps({"role": "user", "content": question, "ts": now}, ensure_ascii=False),
                   json.dumps({"role": "assistant", "content": answer, "ts": now}, ensure_ascii=False))
        pipe.ltrim(key, -settings.history_max_messages, -1)
        pipe.expire(key, 7 * 24 * 3600)
        pipe.execute()
    except redis.RedisError:
        log_event("history_write_failed", logging.WARNING, user_id=user_id)
