from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    data_dir: Path = Path("/data")
    redis_url: str = "redis://127.0.0.1:6379/0"
    secret_key: str = ""
    fernet_key: str = ""
    initial_admin_user: str = "admin"
    initial_admin_password: str = ""

    @property
    def sqlite_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'sqlite' / 'app.db'}"

    @property
    def keys_dir(self) -> Path:
        return self.data_dir / "keys"


settings = Settings()
