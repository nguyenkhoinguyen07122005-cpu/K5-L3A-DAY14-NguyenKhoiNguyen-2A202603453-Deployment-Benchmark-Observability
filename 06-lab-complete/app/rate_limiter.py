"""
Rate limiting (tiêu chí 7) — sliding window 60 giây bằng Redis sorted set.

  • Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request / 60 giây
  • Vượt giới hạn → HTTP 429 + header Retry-After
  • State nằm trong Redis → mọi worker / instance dùng chung, còn nguyên sau khi restart
"""
import hashlib
import time
import uuid

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def _bucket_key(key: str) -> str:
    # Không lưu API key dạng plain text trong Redis
    return "ratelimit:" + hashlib.sha256(key.encode()).hexdigest()[:24]


def check_rate_limit(key: str) -> None:
    limit = settings.rate_limit_per_minute
    bucket = _bucket_key(key)
    now = time.time()
    member = f"{now:.6f}-{uuid.uuid4().hex[:8]}"

    try:
        # MULTI/EXEC: xoá request cũ → thêm request này → đếm, tất cả atomic
        pipe = r.pipeline(transaction=True)
        pipe.zremrangebyscore(bucket, 0, now - WINDOW_SECONDS)
        pipe.zadd(bucket, {member: now})
        pipe.zcard(bucket)
        pipe.expire(bucket, WINDOW_SECONDS + 1)
        _, _, count, _ = pipe.execute()

        if count > limit:
            r.zrem(bucket, member)  # request bị chặn không chiếm chỗ trong cửa sổ
            oldest = r.zrange(bucket, 0, 0, withscores=True)
            retry_after = WINDOW_SECONDS
            if oldest:
                retry_after = max(1, int(oldest[0][1] + WINDOW_SECONDS - now) + 1)
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {limit} requests / {WINDOW_SECONDS}s",
                headers={"Retry-After": str(retry_after),
                         "X-RateLimit-Limit": str(limit),
                         "X-RateLimit-Remaining": "0"},
            )
    except redis.RedisError as exc:
        # Không có Redis thì không đảm bảo được giới hạn → trả 503 thay vì cho qua
        raise HTTPException(status_code=503, detail="Rate limiter unavailable") from exc
