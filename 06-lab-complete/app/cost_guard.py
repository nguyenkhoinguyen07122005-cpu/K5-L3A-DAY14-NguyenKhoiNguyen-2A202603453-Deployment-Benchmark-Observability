"""
Cost guard (tiêu chí 8).

  • Cộng dồn chi phí LLM (tính theo token) vào Redis — key theo ngày và theo tháng (UTC)
  • Tổng chi phí đã đạt DAILY_BUDGET_USD hoặc MONTHLY_BUDGET_USD → HTTP 402
  • Key tự hết hạn (EXPIRE) nên "reset" sang ngày / tháng mới mà không cần cron
"""
from datetime import datetime, timezone

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006


def _keys() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return f"cost:daily:{now:%Y-%m-%d}", f"cost:monthly:{now:%Y-%m}"


def estimate_tokens(text: str) -> int:
    """~4 ký tự / token (ước lượng thô, đủ cho mock LLM)."""
    return max(1, len(text) // 4)


def get_spending() -> dict:
    daily_key, monthly_key = _keys()
    daily, monthly = r.mget(daily_key, monthly_key)
    return {"daily_usd": float(daily or 0), "monthly_usd": float(monthly or 0),
            "daily_budget_usd": settings.daily_budget_usd,
            "monthly_budget_usd": settings.monthly_budget_usd}


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    try:
        spent = get_spending()
    except redis.RedisError as exc:
        raise HTTPException(status_code=503, detail="Cost guard unavailable") from exc

    if spent["daily_usd"] >= settings.daily_budget_usd:
        raise HTTPException(status_code=402,
                            detail=f"Daily budget exhausted (${settings.daily_budget_usd})")
    if spent["monthly_usd"] >= settings.monthly_budget_usd:
        raise HTTPException(status_code=402,
                            detail=f"Monthly budget exhausted (${settings.monthly_budget_usd})")


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = (input_tokens / 1000) * PRICE_INPUT_PER_1K + (output_tokens / 1000) * PRICE_OUTPUT_PER_1K
    daily_key, monthly_key = _keys()
    try:
        pipe = r.pipeline(transaction=True)
        pipe.incrbyfloat(daily_key, cost)
        pipe.expire(daily_key, 2 * 24 * 3600)
        pipe.incrbyfloat(monthly_key, cost)
        pipe.expire(monthly_key, 32 * 24 * 3600)
        pipe.execute()
    except redis.RedisError:
        pass  # request đã trả lời xong; mất 1 lần ghi cost không nên làm user nhận lỗi
    return cost
