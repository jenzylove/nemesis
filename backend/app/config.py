from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    app_env: Literal["development", "test", "production"] = "development"
    port: int = 8080
    log_level: str = "INFO"
    cors_allowed_origins: str = "http://localhost:3000,http://localhost:4173"

    ethereum_rpc_url: str = ""
    base_rpc_url: str = ""
    rpc_timeout_seconds: float = Field(default=20.0, gt=0, le=120)

    firestore_project_id: str = ""
    firestore_database: str = "(default)"
    firestore_cases_collection: str = "cases"

    google_cloud_project: str = ""
    google_cloud_location: str = "global"
    google_api_key: str = ""
    google_genai_use_vertexai: bool = False
    gemini_model: str = "gemini-3.5-flash"
    adk_app_name: str = "nemesis"
    pubsub_topic: str = "nemesis-case-events"
    cloud_run_service_url: str = ""
    internal_service_account: str = ""
    monitoring_max_blocks: int = Field(default=20, ge=1, le=100)

    @property
    def cors_origins(self) -> list[str]:
        return [value.strip() for value in self.cors_allowed_origins.split(",") if value.strip()]

    @model_validator(mode="after")
    def validate_production(self):
        if self.app_env != "production":
            return self
        missing = []
        if not self.ethereum_rpc_url:
            missing.append("ETHEREUM_RPC_URL")
        if not self.base_rpc_url:
            missing.append("BASE_RPC_URL")
        if not self.firestore_project_id:
            missing.append("FIRESTORE_PROJECT_ID")
        if not (self.google_api_key or self.google_genai_use_vertexai):
            missing.append("GOOGLE_API_KEY or GOOGLE_GENAI_USE_VERTEXAI=TRUE")
        if self.google_genai_use_vertexai and not self.google_cloud_project:
            missing.append("GOOGLE_CLOUD_PROJECT")
        if missing:
            raise ValueError("production configuration is incomplete: " + ", ".join(missing))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
