"""Application configuration using Pydantic Settings."""
from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application
    ENVIRONMENT: str = Field(default="development", description="Environment: development, staging, production")
    SECRET_KEY: str = Field(default="dev-secret-key-change-in-production-min-32-chars", description="JWT secret key")
    ALGORITHM: str = Field(default="HS256", description="JWT algorithm")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, description="Access token expiry in minutes")
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, description="Refresh token expiry in days")

    # Database
    DATABASE_URL: str = Field(default="sqlite+aiosqlite:///./nte.db", description="Database connection URL")

    # Redis
    REDIS_URL: str = Field(default="redis://localhost:6379/0", description="Redis connection URL")

    # NIPOST Postcode API
    POSTCODE_API_URL: str = Field(default="https://api.postcode.gov.ng", description="NIPOST API base URL")
    POSTCODE_API_KEY: Optional[str] = Field(default=None, description="NIPOST API key (optional for dev mock mode)")

    # CORS
    CORS_ORIGINS: List[str] = Field(default=["http://localhost:3000", "http://127.0.0.1:3000"], description="Allowed CORS origins")

    # Email (for notifications, password reset - optional)
    SMTP_HOST: Optional[str] = Field(default=None, description="SMTP host")
    SMTP_PORT: int = Field(default=587, description="SMTP port")
    SMTP_USER: Optional[str] = Field(default=None, description="SMTP username")
    SMTP_PASSWORD: Optional[str] = Field(default=None, description="SMTP password")
    EMAIL_FROM: str = Field(default="Nte <noreply@nte.ng>", description="From email address")

    # Frontend
    API_URL: str = Field(default="http://localhost:8000", description="Backend API URL")
    FRONTEND_URL: str = Field(default="http://localhost:3000", description="Frontend URL")

    # Google OAuth (optional)
    GOOGLE_CLIENT_ID: Optional[str] = Field(default=None, description="Google OAuth client ID")
    GOOGLE_CLIENT_SECRET: Optional[str] = Field(default=None, description="Google OAuth client secret")

    # Logging
    LOG_LEVEL: str = Field(default="INFO", description="Log level")
    LOG_FORMAT: str = Field(default="json", description="Log format: json or console")

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT.lower() == "development"

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"


settings = Settings()
