"""Application configuration settings."""
from functools import lru_cache
from typing import List, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application
    ENVIRONMENT: str = Field(default="development", description="Runtime environment")
    SECRET_KEY: str = Field(..., description="Secret key for JWT signing")
    ALGORITHM: str = Field(default="HS256", description="JWT algorithm")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, description="Access token expiry in minutes")
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, description="Refresh token expiry in days")

    # Database
    DATABASE_URL: str = Field(..., description="Database connection URL")

    # Redis
    REDIS_URL: str = Field(default="redis://localhost:6379/0", description="Redis connection URL")

    # NIPOST Postcode API
    POSTCODE_API_URL: str = Field(default="https://api.postcode.gov.ng", description="NIPOST Postcode API base URL")
    POSTCODE_API_KEY: Optional[str] = Field(default=None, description="NIPOST Postcode API key")

    # CORS
    CORS_ORIGINS: List[str] = Field(default=["http://localhost:3000"], description="Allowed CORS origins")

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | List[str]) -> List[str]:
        """Parse CORS origins from comma-separated string or list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    # Email (optional)
    SMTP_HOST: Optional[str] = Field(default=None, description="SMTP host")
    SMTP_PORT: int = Field(default=587, description="SMTP port")
    SMTP_USER: Optional[str] = Field(default=None, description="SMTP username")
    SMTP_PASSWORD: Optional[str] = Field(default=None, description="SMTP password")
    EMAIL_FROM: str = Field(default="Nte <noreply@usuk.ng>", description="From email address")

    # Frontend
    API_URL: str = Field(default="http://localhost:8000", description="Backend API URL")
    FRONTEND_URL: str = Field(default="http://localhost:3000", description="Frontend URL")

    # Google OAuth (optional)
    GOOGLE_CLIENT_ID: Optional[str] = Field(default=None, description="Google OAuth client ID")
    GOOGLE_CLIENT_SECRET: Optional[str] = Field(default=None, description="Google OAuth client secret")

    # Logging
    LOG_LEVEL: str = Field(default="INFO", description="Log level")
    LOG_FORMAT: str = Field(default="json", description="Log format (json or text)")

    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.ENVIRONMENT.lower() == "development"

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.ENVIRONMENT.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()