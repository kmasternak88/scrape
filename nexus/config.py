import os
from typing import Optional, Any
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    env: str = Field(default="production")
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    api_key: str = Field(default="nexus_master_secret_key_change_me")
    db_path: str = Field(default="sqlite+aiosqlite:///nexus.db")
    redis_url: str = Field(default="redis://localhost:6379/0")
    max_concurrent_browsers: int = Field(default=10)
    default_timeout: int = Field(default=30000)
    proxy_list_path: Optional[str] = Field(default=None)
    captcha_solver_key: Optional[str] = Field(default=None)

    model_config = SettingsConfigDict(
        env_prefix="NEXUS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def __getattr__(self, name: str) -> Any:
        lower_name = name.lower()
        if lower_name in self.model_fields:
            return getattr(self, lower_name)
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        lower_name = name.lower()
        if lower_name in self.model_fields:
            super().__setattr__(lower_name, value)
        else:
            super().__setattr__(name, value)

settings = Settings()
