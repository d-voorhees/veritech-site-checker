from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application configuration.

    All values are overridable via environment variables so product identity
    and behavior are configured, not hardcoded, per the product requirements.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_domain: str = "localhost"
    app_url: str = "http://localhost:3000"
    marketing_site_url: str = "https://veritechdiligence.com"
    product_name: str = "Veritech Scan"
    parent_brand: str = "Veritech Diligence"
    report_name: str = "Technical Acquisition Brief"

    database_url: str = ""

    # Fly.io deployment settings. fly_database_url mirrors the DATABASE_URL
    # style secret Fly Postgres/Managed Postgres attaches under a
    # Fly-specific name; fly_api_token/fly_app_name/fly_primary_region drive
    # the Fly Machines API client (app/services/fly_machines.py) that
    # creates the on-demand scan-runner Machine. FLY_API_TOKEN is
    # server-side only and must never be sent to the browser.
    fly_app_name: str = ""
    fly_api_token: str = ""
    fly_primary_region: str = "iad"
    fly_database_url: str = ""

    jwt_secret: str = "dev-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 1440

    initial_admin_email: str = "admin@example.com"
    initial_admin_password: str = "change-me"

    scan_max_total_minutes: int = 10
    scan_default_request_delay_seconds: float = 1.5
    scan_max_pages: int = 50
    scan_page_timeout_seconds: int = 15
    scan_create_rate_limit_per_hour: int = 10
    scan_create_rate_limit_per_day: int = 3

    google_pagespeed_api_key: str = ""
    sentry_dsn: str = ""

    # --- Magic-link auth + Brevo/MailerLite (see docs on the free-launch
    # signup build). Session cookies for magic-link users reuse
    # jwt_secret/JWT_SECRET above — same cookie, same signing purpose as
    # password login, not a different one, so no separate session secret.
    # The verify link's base URL reuses app_url/APP_URL for the same reason.
    magic_link_token_expires_minutes: int = 20
    magic_link_request_rate_limit_per_hour: int = 5

    brevo_api_key: str = ""
    brevo_magic_link_template_id: int | None = None
    # Must be a sender verified in the Brevo account, or transactional sends
    # are rejected outright.
    brevo_sender_email: str = ""
    brevo_sender_name: str = "Veritech Site Checker"

    mailerlite_api_key: str = ""
    mailerlite_group_id: str = "196262875934754744"

    # Slack Incoming Webhook for scan-lifecycle notifications, and the
    # inbox that gets a copy of every completed scan's results.
    slack_webhook_url: str = ""
    results_notification_email: str = ""

    @field_validator("brevo_magic_link_template_id", mode="before")
    @classmethod
    def _blank_template_id_is_unset(cls, value: object) -> object:
        # An unset BREVO_MAGIC_LINK_TEMPLATE_ID env var arrives as "", which
        # doesn't parse as int | None on its own.
        return None if value == "" else value

    artifact_storage_backend: str = "local"
    artifact_storage_local_path: str = "/data/artifacts"

    log_format: str = "console"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def resolved_database_url(self) -> str:
        """DATABASE_URL wins if set (local dev, tests); otherwise fall back
        to FLY_DATABASE_URL (as attached by Fly Postgres in production),
        then a native-Postgres-friendly local default.
        """
        return (
            self.database_url
            or self.fly_database_url
            or "postgresql+psycopg://veritech_scan:change-me@127.0.0.1:5432/veritech_scan"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
