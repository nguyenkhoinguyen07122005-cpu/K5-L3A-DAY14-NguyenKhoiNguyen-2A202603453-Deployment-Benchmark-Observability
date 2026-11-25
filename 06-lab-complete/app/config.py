"""
Config — 12-Factor: mọi cấu hình đọc từ biến môi trường.

Không có secret nào được hard-code ở đây: AGENT_API_KEY mặc định là chuỗi rỗng,
và khi rỗng thì auth từ chối MỌI request (fail closed).
"""
import os
from dataclasses import dataclass, field


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    port: int = field(default_factory=lambda: _env_int("PORT", 8000))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())

    # Secrets — chỉ đọc từ env
    agent_api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))

    # Redis — state dùng chung giữa các worker / instance
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))

    # Bảo vệ API
    rate_limit_per_minute: int = field(default_factory=lambda: _env_int("RATE_LIMIT_PER_MINUTE", 10))
    daily_budget_usd: float = field(default_factory=lambda: _env_float("DAILY_BUDGET_USD", 1.0))
    monthly_budget_usd: float = field(default_factory=lambda: _env_float("MONTHLY_BUDGET_USD", 10.0))

    # Conversation history giữ tối đa bao nhiêu tin nhắn / user (lưu Redis)
    history_max_messages: int = field(default_factory=lambda: _env_int("HISTORY_MAX_MESSAGES", 20))


settings = Settings()
