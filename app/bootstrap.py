import json
import os
import secrets
import tempfile

from cryptography.fernet import Fernet

from app import config


def bootstrap_keys() -> tuple[str, str]:
    """首次启动生成 secret_key 与 fernet_key,持久化到 data_dir/keys;后续启动加载。
    返回 (secret_key, fernet_key)。绝不在代码里硬编码弱默认。

    通过模块引用 config.settings 读取路径,以便测试 reload(config) 后立即生效。

    写入采用原子方式(临时文件 + os.replace):避免进程被中断时 keys.json 写一半,
    导致下次启动 JSON 解析失败 —— 删除 keys.json 会丢失 fernet_key,使历史加密凭据无法解密。"""
    # 优先使用环境变量提供的密钥(spec §11);否则首启自动生成并持久化。
    # 必须成对提供:只给一个会让另一个悄悄回落到生成值,造成"以为固定了其实没有"。
    env_sk = config.settings.secret_key
    env_fk = config.settings.fernet_key
    if env_sk and env_fk:
        return env_sk, env_fk
    if env_sk or env_fk:
        raise RuntimeError("APP_SECRET_KEY 与 APP_FERNET_KEY 必须同时提供,或都不提供")
    keys_dir = config.settings.keys_dir
    keys_dir.mkdir(parents=True, exist_ok=True)
    key_file = keys_dir / "keys.json"
    if key_file.exists():
        # 修复历史/手动编辑遗留的宽松权限(fernet_key 可解密所有存储凭据)
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass
        data = json.loads(key_file.read_text())
        return data["secret_key"], data["fernet_key"]

    secret_key = secrets.token_urlsafe(48)
    fernet_key = Fernet.generate_key().decode("ascii")
    payload = json.dumps({"secret_key": secret_key, "fernet_key": fernet_key})

    tmp_fd, tmp_path = tempfile.mkstemp(dir=keys_dir, prefix=".keys.", suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w") as f:
            f.write(payload)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, key_file)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return secret_key, fernet_key
