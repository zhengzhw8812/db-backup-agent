from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    data_dir: Path = Path("/data")
    static_dir: Path = Path("/app/static")
    redis_url: str = "redis://127.0.0.1:6379/0"
    secret_key: str = ""
    fernet_key: str = ""
    initial_admin_user: str = "admin"
    initial_admin_password: str = ""
    # 是否在本进程内启动 APScheduler。多 worker 部署时只应有一个进程为 true,
    # 其余设为 false,避免同一 cron 被多次触发(配合连接级互斥锁进一步兜底)。
    scheduler_enabled: bool = True
    # 会话 cookie 是否加 Secure 标记。生产应在 TLS 终结代理后置为 true。
    cookie_secure: bool = False

    @property
    def sqlite_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'sqlite' / 'app.db'}"

    @property
    def keys_dir(self) -> Path:
        return self.data_dir / "keys"


settings = Settings()
