from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # GCP
    google_cloud_project: str = ""
    google_cloud_region: str = "asia-south1"

    # Vertex AI
    vertex_ai_model_flash: str = "gemini-2.5-flash"
    vertex_ai_model_pro: str = "gemini-2.5-flash"

    # News
    news_api_key: str = ""

    # Cache — rolling TTL, no date in keys so cache survives midnight
    redis_url: str = ""
    gainers_list_ttl: int = 7200    # 2 h (refreshes during trading day)
    analysis_ttl: int = 86400       # 24 h (analyses stay warm overnight)

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    # Auth
    jwt_secret: str = "dev-secret-change-in-production-stockcoach-2024"
    jwt_expire_days: int = 30

    # Feature flags
    mock_ai: bool = False
    top_gainers_count: int = 20
    prewarm_concurrency: int = 3  # max parallel AI pre-warm calls

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, v: str) -> str:
        return v

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def use_redis(self) -> bool:
        return bool(self.redis_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
