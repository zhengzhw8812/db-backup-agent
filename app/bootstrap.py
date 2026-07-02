import json
import secrets

from cryptography.fernet import Fernet

from app import config


def bootstrap_keys() -> tuple[str, str]:
    """首次启动生成 secret_key 与 fernet_key,持久化到 data_dir/keys;后续启动加载。
    返回 (secret_key, fernet_key)。绝不在代码里硬编码弱默认。

    通过模块引用 config.settings 读取路径,以便测试 reload(config) 后立即生效。"""
    keys_dir = config.settings.keys_dir
    keys_dir.mkdir(parents=True, exist_ok=True)
    key_file = keys_dir / "keys.json"
    if key_file.exists():
        data = json.loads(key_file.read_text())
        return data["secret_key"], data["fernet_key"]
    secret_key = secrets.token_urlsafe(48)
    fernet_key = Fernet.generate_key().decode("ascii")
    key_file.write_text(json.dumps({"secret_key": secret_key, "fernet_key": fernet_key}))
    try:
        key_file.chmod(0o600)
    except OSError:
        pass
    return secret_key, fernet_key
