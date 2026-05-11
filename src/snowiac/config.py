"""Centralized configuration loaded from environment variables / .env."""
from functools import lru_cache

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Foundry runtime env vars take precedence over local .env
load_dotenv(override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Foundry
    foundry_project_endpoint: str = ""
    foundry_model_deployment_name: str = "gpt-4.1-mini"

    # ServiceNow
    snow_instance_url: str = ""
    snow_user: str = ""
    snow_password: str = ""
    snowiac_use_mocks: bool = True

    # GitHub
    github_token: str = ""
    github_repo: str = ""
    github_base_branch: str = "main"

    # Azure
    azure_subscription_id: str = ""
    azure_default_resource_group: str = "MultiAgentSnow"
    azure_default_location: str = "eastus"

    # Webhook
    webhook_hmac_secret: str = "change-me"

    # Persistence
    snowiac_db_path: str = "snowiac.db"
    # If set (e.g. postgresql://user:pass@host:5432/snowiac?sslmode=require)
    # the Postgres backend is used instead of SQLite.
    database_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
