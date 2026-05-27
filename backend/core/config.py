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
    vertex_ai_model_flash: str = "gemini-1.5-flash-002"
    vertex_ai_model_pro: str = "gemini-1.5-pro-002"

    # News
    news_api_key: str = ""

    # Cache
    redis_url: str = ""
    gainers_list_ttl: int = 1800   # 30 min
    analysis_ttl: int = 21600       # 6 hours

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    # Feature flags
    mock_ai: bool = False
    top_gainers_count: int = 20

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
